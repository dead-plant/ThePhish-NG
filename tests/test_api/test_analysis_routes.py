"""Tests for the /api/analyses routes."""

from app.services.analysis import pipeline, tracking


class DummyTask:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[tuple] = []

    def delay(self, *args, **kwargs):
        if self.exc is not None:
            raise self.exc
        self.calls.append((args, kwargs))


class TestCreateAnalysis:
    def test_valid_request_starts_analysis(self, client, fake_redis, monkeypatch):
        dummy = DummyTask()
        monkeypatch.setattr(pipeline, "run_analysis", dummy)

        response = client.post("/api/analyses", json={"mail_uid": 5})

        assert response.status_code == 202
        body = response.get_json()
        assert body["status"] == "pending"
        assert body["mail_uid"] == 5
        assert body["analysis_id"]
        assert body["created_at"]
        assert len(dummy.calls) == 1

    def test_invalid_uid_returns_400(self, client, fake_redis):
        response = client.post("/api/analyses", json={"mail_uid": "abc"})
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "invalid_mail_uid"

    def test_missing_body_returns_400(self, client, fake_redis):
        response = client.post("/api/analyses")
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "invalid_mail_uid"

    def test_queue_failure_returns_503_and_records_failure(self, client, fake_redis, monkeypatch):
        monkeypatch.setattr(pipeline, "run_analysis", DummyTask(exc=RuntimeError("broker down")))

        response = client.post("/api/analyses", json={"mail_uid": 5})

        assert response.status_code == 503
        assert response.get_json()["error"]["code"] == "analysis_backend_unavailable"
        state = next(iter(fake_redis.hashes.values()))
        assert state["status"] == "failed"

    def test_storage_failure_returns_503(self, client, fake_redis):
        fake_redis.fail_on.add("hset")
        response = client.post("/api/analyses", json={"mail_uid": 5})
        assert response.status_code == 503
        assert response.get_json()["error"]["code"] == "analysis_storage_unavailable"


class TestGetAnalysis:
    def test_returns_current_state(self, client, fake_redis):
        state = tracking.create_analysis("aid1", 9)
        response = client.get("/api/analyses/aid1")
        assert response.status_code == 200
        assert response.get_json() == state

    def test_unknown_analysis_returns_404(self, client, fake_redis):
        response = client.get("/api/analyses/unknown")
        assert response.status_code == 404
        assert response.get_json()["error"]["code"] == "analysis_not_found"

    def test_storage_failure_returns_503(self, client, fake_redis):
        fake_redis.fail_on.add("hgetall")
        response = client.get("/api/analyses/aid1")
        assert response.status_code == 503
        assert response.get_json()["error"]["code"] == "analysis_storage_unavailable"


class TestGetAnalysisLog:
    def test_returns_entries_in_order(self, client, fake_redis):
        tracking.create_analysis("aid1", 9)
        tracking.append_log_entry("aid1", "info", "first")
        tracking.append_log_entry("aid1", "warning", "second")

        response = client.get("/api/analyses/aid1/log")

        assert response.status_code == 200
        entries = response.get_json()
        assert [(entry["seq"], entry["level"], entry["message"]) for entry in entries] == [
            (0, "info", "first"),
            (1, "warning", "second"),
        ]
        assert all(entry["timestamp"] for entry in entries)

    def test_unknown_analysis_returns_404(self, client, fake_redis):
        response = client.get("/api/analyses/unknown/log")
        assert response.status_code == 404
        assert response.get_json()["error"]["code"] == "analysis_not_found"


class TestStreamAnalysis:
    def test_streams_sse_and_stops_after_terminal_state(self, client, fake_redis):
        tracking.create_analysis("aid1", 9)
        tracking.append_log_entry("aid1", "info", "stored entry")
        tracking.set_state_fields("aid1", status="finished", verdict="Safe", finished_at=tracking.utc_now_iso())

        response = client.get("/api/analyses/aid1/stream")

        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        text = response.get_data(as_text=True)  # consuming the whole body proves the stream terminates
        assert "event: log" in text
        assert "stored entry" in text
        assert "event: status" in text
        assert '"status": "finished"' in text
        assert '"verdict": "Safe"' in text

    def test_unknown_analysis_returns_404(self, client, fake_redis):
        response = client.get("/api/analyses/unknown/stream")
        assert response.status_code == 404
        assert response.get_json()["error"]["code"] == "analysis_not_found"
