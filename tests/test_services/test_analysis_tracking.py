"""Tests for analysis state tracking, log storage and SSE streaming."""

import json

import pytest

from app.services.analysis import tracking
from app.services.analysis.errors import AnalysisNotFoundError, AnalysisStorageError

ANALYSIS_ID = "a1b2c3"
RETENTION_SECONDS = 7 * 86400  # retention_days = 7 in config-example/app.conf


def parse_events(chunks):
    """Parse SSE chunks into (event, data) tuples, dropping keepalives."""
    events = []
    for chunk in chunks:
        if chunk.startswith(":"):
            continue
        event = data = None
        for line in chunk.strip().splitlines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        events.append((event, data))
    return events


class TestState:
    def test_create_and_get_roundtrip(self, fake_redis):
        created = tracking.create_analysis(ANALYSIS_ID, 42)
        state = tracking.get_analysis(ANALYSIS_ID)
        assert state == created
        assert state["analysis_id"] == ANALYSIS_ID
        assert state["mail_uid"] == 42
        assert state["status"] == "pending"
        assert state["created_at"]
        # optional fields are not returned while empty
        assert "verdict" not in state and "error" not in state and "case_id" not in state

    def test_create_sets_retention(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        state_key = next(iter(fake_redis.hashes))
        assert fake_redis.expirations[state_key] == RETENTION_SECONDS

    def test_get_missing_analysis(self, fake_redis):
        with pytest.raises(AnalysisNotFoundError):
            tracking.get_analysis("unknown")

    def test_get_with_redis_down(self, fake_redis):
        fake_redis.fail_on.add("hgetall")
        with pytest.raises(AnalysisStorageError):
            tracking.get_analysis(ANALYSIS_ID)

    def test_create_with_redis_down(self, fake_redis):
        fake_redis.fail_on.add("hset")
        with pytest.raises(AnalysisStorageError):
            tracking.create_analysis(ANALYSIS_ID, 42)

    def test_set_state_fields_publishes_status(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        tracking.set_state_fields(ANALYSIS_ID, status=tracking.STATUS_RUNNING, started_at=tracking.utc_now_iso())
        channel, payload = fake_redis.published[-1]
        event = json.loads(payload)
        assert event["type"] == "status"
        assert event["status"] == "running"

    def test_mark_failed_records_error(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        tracking.mark_failed(ANALYSIS_ID, "something broke")
        state = tracking.get_analysis(ANALYSIS_ID)
        assert state["status"] == "failed"
        assert state["error"] == "something broke"
        assert state["finished_at"]

    def test_mark_failed_swallows_redis_errors(self, fake_redis):
        fake_redis.fail_on.add("hset")
        tracking.mark_failed(ANALYSIS_ID, "err")  # must not raise


class TestLog:
    def test_append_and_get_preserves_order(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        tracking.append_log_entry(ANALYSIS_ID, "info", "first")
        tracking.append_log_entry(ANALYSIS_ID, "warning", "second")
        entries = tracking.get_analysis_log(ANALYSIS_ID)
        assert [(entry["seq"], entry["level"], entry["message"]) for entry in entries] == [
            (0, "info", "first"),
            (1, "warning", "second"),
        ]
        assert all(entry["timestamp"] for entry in entries)

    def test_get_log_of_missing_analysis(self, fake_redis):
        with pytest.raises(AnalysisNotFoundError):
            tracking.get_analysis_log("unknown")

    def test_log_sets_retention(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        tracking.append_log_entry(ANALYSIS_ID, "info", "first")
        log_keys = [key for key in fake_redis.expirations if key.endswith(":log")]
        assert log_keys and fake_redis.expirations[log_keys[0]] == RETENTION_SECONDS

    def test_logger_defangs_iocs(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        logger = tracking.AnalysisLogger(ANALYSIS_ID)
        logger.info("Found observable url: http://evil.example.com/login")
        stored = tracking.get_analysis_log(ANALYSIS_ID)[0]["message"]
        assert stored == "Found observable url: hXXp://evil[.]example[.]com/login"
        assert logger.entries[0]["message"] == stored  # in-memory copy matches

    def test_logger_keeps_entries_in_memory_on_redis_failure(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        logger = tracking.AnalysisLogger(ANALYSIS_ID)
        logger.info("stored")
        fake_redis.fail_on.add("rpush")
        logger.warning("memory only")  # must not raise
        assert [entry["message"] for entry in logger.entries] == ["stored", "memory only"]
        fake_redis.fail_on.clear()
        assert len(tracking.get_analysis_log(ANALYSIS_ID)) == 1


class TestStream:
    def test_stream_of_missing_analysis_raises_before_streaming(self, fake_redis):
        with pytest.raises(AnalysisNotFoundError):
            tracking.stream_analysis_events("unknown")

    def test_terminal_analysis_replays_and_stops(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        tracking.append_log_entry(ANALYSIS_ID, "info", "first")
        tracking.append_log_entry(ANALYSIS_ID, "info", "second")
        tracking.set_state_fields(ANALYSIS_ID, status="finished", verdict="Safe", finished_at=tracking.utc_now_iso())

        chunks = list(tracking.stream_analysis_events(ANALYSIS_ID))
        events = parse_events(chunks)
        assert [event for event, _ in events] == ["log", "log", "status"]
        assert events[0][1]["message"] == "first" and events[0][1]["seq"] == 0
        assert events[2][1] == {"type": "status", "status": "finished", "verdict": "Safe"}
        # SSE framing: log events carry their sequence number as the event id
        assert chunks[0].startswith("event: log\nid: 0\ndata: ")
        assert chunks[0].endswith("\n\n")

    def test_live_events_after_replay(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        stream = tracking.stream_analysis_events(ANALYSIS_ID)

        (event, data), = parse_events([next(stream)])
        assert event == "status" and data["status"] == "pending"

        tracking.append_log_entry(ANALYSIS_ID, "info", "live entry")
        (event, data), = parse_events([next(stream)])
        assert event == "log" and data["message"] == "live entry"

        tracking.mark_failed(ANALYSIS_ID, "boom")
        (event, data), = parse_events([next(stream)])
        assert event == "status" and data["status"] == "failed" and data["error"] == "boom"
        with pytest.raises(StopIteration):
            next(stream)

    def test_missed_pubsub_terminal_state_is_recovered(self, fake_redis, monkeypatch):
        monkeypatch.setattr(tracking, "STATE_CHECK_INTERVAL", 0.0)
        tracking.create_analysis(ANALYSIS_ID, 42)
        stream = tracking.stream_analysis_events(ANALYSIS_ID)
        next(stream)  # initial status event

        # updates whose pub/sub events all get lost
        fake_redis.mute_publish = True
        tracking.append_log_entry(ANALYSIS_ID, "info", "missed entry")
        tracking.set_state_fields(ANALYSIS_ID, status="finished", verdict="Safe")

        events = parse_events(list(stream))
        assert ("log", {"seq": 0, "level": "info", "message": "missed entry", "timestamp": events[0][1]["timestamp"]}) == events[0]
        assert events[-1][0] == "status" and events[-1][1]["status"] == "finished"

    def test_keepalive_is_sent(self, fake_redis, monkeypatch):
        monkeypatch.setattr(tracking, "KEEPALIVE_INTERVAL", 0.0)
        tracking.create_analysis(ANALYSIS_ID, 42)
        stream = tracking.stream_analysis_events(ANALYSIS_ID)
        next(stream)  # initial status event
        assert next(stream) == ": keepalive\n\n"

    def test_redis_failure_ends_stream_and_closes_pubsub(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        stream = tracking.stream_analysis_events(ANALYSIS_ID)
        next(stream)  # initial status event
        fake_redis.fail_on.add("get_message")
        with pytest.raises(StopIteration):
            next(stream)
        assert all(pubsub.closed for pubsub in fake_redis.pubsubs) or not fake_redis.pubsubs

    def test_terminal_stream_closes_pubsub(self, fake_redis):
        tracking.create_analysis(ANALYSIS_ID, 42)
        tracking.set_state_fields(ANALYSIS_ID, status="failed", error="x")
        list(tracking.stream_analysis_events(ANALYSIS_ID))
        assert all(pubsub.closed for pubsub in fake_redis.pubsubs) or not fake_redis.pubsubs
