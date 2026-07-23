"""Tests for starting analyses and the Celery task workflow."""

import email.message

import pytest
from kombu.exceptions import OperationalError

from app.repositories import mailbox
from app.services.analysis import analyzers, case_builder, pipeline, tracking
from app.services.analysis.errors import AnalysisQueueError, InvalidMailUidError

ANALYSIS_ID = "a1b2c3"


class DummyTask:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[tuple] = []

    def delay(self, *args, **kwargs):
        if self.exc is not None:
            raise self.exc
        self.calls.append((args, kwargs))


class TestStartAnalysis:
    def test_valid_uid_queues_task(self, fake_redis, monkeypatch):
        dummy = DummyTask()
        monkeypatch.setattr(pipeline, "run_analysis", dummy)

        state = pipeline.start_analysis(7)

        assert state["status"] == "pending"
        assert state["mail_uid"] == 7
        assert state["created_at"]
        assert dummy.calls == [((state["analysis_id"], 7), {})]
        assert tracking.get_analysis(state["analysis_id"]) == state

    def test_numeric_string_uid_is_accepted(self, fake_redis, monkeypatch):
        dummy = DummyTask()
        monkeypatch.setattr(pipeline, "run_analysis", dummy)
        state = pipeline.start_analysis("42")
        assert state["mail_uid"] == 42

    @pytest.mark.parametrize("mail_uid", [None, "", "abc", "-1", -1, 0, True, False, 3.5, [1], {"uid": 1}])
    def test_invalid_uid_is_rejected(self, mail_uid):
        with pytest.raises(InvalidMailUidError):
            pipeline.start_analysis(mail_uid)

    def test_queue_failure_records_failed_state(self, fake_redis, monkeypatch):
        dummy = DummyTask(exc=OperationalError("broker down"))
        monkeypatch.setattr(pipeline, "run_analysis", dummy)

        with pytest.raises(AnalysisQueueError):
            pipeline.start_analysis(7)

        state_key = next(iter(fake_redis.hashes))
        state = fake_redis.hashes[state_key]
        assert state["status"] == "failed"
        assert state["error"] == "The analysis task could not be queued"
        assert state["finished_at"]


class TestExecuteAnalysis:
    def test_fatal_fetch_failure_is_recorded(self, fake_redis, monkeypatch):
        tracking.create_analysis(ANALYSIS_ID, 5)

        def raise_not_found(mail_uid):
            raise mailbox.EmailNotFoundError(f"No unread email with UID {mail_uid}")

        monkeypatch.setattr(pipeline.mailbox, "fetch_analyzable_eml", raise_not_found)
        pipeline._execute_analysis(ANALYSIS_ID, 5)

        state = tracking.get_analysis(ANALYSIS_ID)
        assert state["status"] == "failed"
        assert "UID 5" in state["error"]
        assert state["started_at"] and state["finished_at"]
        assert any(entry["level"] == "error" for entry in tracking.get_analysis_log(ANALYSIS_ID))

    def test_unexpected_exception_is_recorded(self, fake_redis, monkeypatch):
        tracking.create_analysis(ANALYSIS_ID, 5)

        def explode(mail_uid):
            raise RuntimeError("boom")

        monkeypatch.setattr(pipeline.mailbox, "fetch_analyzable_eml", explode)
        pipeline._execute_analysis(ANALYSIS_ID, 5)

        state = tracking.get_analysis(ANALYSIS_ID)
        assert state["status"] == "failed"
        assert state["error"] == "Unexpected internal error (RuntimeError)"
        assert state["finished_at"]
        # the raw exception details stay out of the analysis log
        assert all("boom" not in entry["message"] for entry in tracking.get_analysis_log(ANALYSIS_ID))

    def test_successful_workflow_records_finished_state(self, fake_redis, monkeypatch):
        tracking.create_analysis(ANALYSIS_ID, 5)
        built = case_builder.BuiltCase(case={"_id": "~case1", "number": 42, "title": "[ThePhish] subject"}, task_ids={})
        stages = []

        monkeypatch.setattr(pipeline.mailbox, "fetch_analyzable_eml", lambda uid: (email.message.Message(), "user@example.com"))
        monkeypatch.setattr(pipeline.case_builder.CaseBuilder, "build_case", lambda self, msg: built)
        monkeypatch.setattr(pipeline.notifications, "send_analysis_started", lambda *args: stages.append("started"))
        monkeypatch.setattr(pipeline.analyzers.AnalyzerRunner, "run", lambda self, b: analyzers.AnalysisOutcome(verdict="Safe", summary_lines=["Analyzer reports: 1 collected, 0 failed"]))
        monkeypatch.setattr(pipeline.case_builder.CaseBuilder, "finalize_case", lambda self, b, verdict: stages.append("finalized"))
        monkeypatch.setattr(pipeline.notifications, "send_analysis_result", lambda *args: stages.append("result"))

        pipeline._execute_analysis(ANALYSIS_ID, 5)

        state = tracking.get_analysis(ANALYSIS_ID)
        assert state["status"] == "finished"
        assert state["verdict"] == "Safe"
        assert state["case_id"] == "~case1"
        assert state["case_number"] == "42"
        assert state["finished_at"]
        assert stages == ["started", "finalized", "result"]
        messages = [entry["message"] for entry in tracking.get_analysis_log(ANALYSIS_ID)]
        assert "The email has been classified as Safe" in messages
