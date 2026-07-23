"""Tests for the EventSink seam: stage injection, event ordering, isolation, snapshots."""

import pytest

from app.repositories import thehive
from app.services.analysis import tracking
from app.services.analysis.analyzers import AnalysisOutcome, AnalyzerRunner
from app.services.analysis.case_builder import CaseBuilder, BuiltCase
from app.services.analysis.notifications import Notifier

from tests.test_services.test_analysis_notifications import MAILER, ResponderStub

BUILT = BuiltCase(case={"_id": "case1", "number": 7, "title": "[ThePhish] x"}, task_ids={"ThePhish result": "task-result"})


class RecordingEventSink:
    """Lightweight in-memory sink used to assert emitted events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.events.append(("info", message))

    def warning(self, message: str) -> None:
        self.events.append(("warning", message))

    def error(self, message: str) -> None:
        self.events.append(("error", message))


@pytest.fixture()
def events():
    return RecordingEventSink()


class TestStageConstruction:
    def test_stages_accept_any_event_sink(self, events):
        # every stage takes the sink once, at construction time
        for stage_type in (CaseBuilder, AnalyzerRunner, Notifier):
            stage = stage_type(events)
            assert stage._events is events

    def test_case_builder_reports_through_injected_sink(self, events):
        # schemas.microsoft.com is whitelisted in config-example/whitelist.json
        kept = CaseBuilder(events)._filter_whitelisted("domain", ["schemas.microsoft.com", "ok.test"])

        assert kept == ["ok.test"]
        assert events.events == [("info", "Skipped whitelisted domain: schemas.microsoft.com")]


class TestEmittedEventsAndOrdering:
    def test_malicious_finalization_emits_export_then_close(self, monkeypatch, events):
        monkeypatch.setattr(thehive, "export_case", lambda case_id, misp_id: None)
        monkeypatch.setattr(thehive, "close_case", lambda **kwargs: None)

        CaseBuilder(events).finalize_case(BUILT, "Malicious")

        assert events.events == [
            ("info", "Exported the case to MISP"),
            ("info", "Closed the case as TruePositive"),
        ]

    def test_export_failure_emits_warning_before_close(self, monkeypatch, events):
        def export_error(case_id, misp_id):
            raise thehive.TheHiveApiError("misp down")

        monkeypatch.setattr(thehive, "export_case", export_error)
        monkeypatch.setattr(thehive, "close_case", lambda **kwargs: None)

        CaseBuilder(events).finalize_case(BUILT, "Malicious")

        assert [level for level, _ in events.events] == ["warning", "info"]
        assert "Could not export the case to MISP" in events.events[0][1]
        assert events.events[1] == ("info", "Closed the case as TruePositive")

    def test_notifier_failure_emits_warning(self, monkeypatch, events):
        ResponderStub(monkeypatch, [])
        Notifier(events).send_analysis_started(
            BuiltCase(case=BUILT.case, task_ids={"ThePhish notification": "task-notif"}), "user@example.com"
        )

        assert events.events == [("warning", "Could not send the notification email: no mail responder is enabled")]


class TestIsolationBetweenExecutions:
    def test_simultaneous_stages_do_not_share_events(self, events):
        other = RecordingEventSink()
        builder_a = CaseBuilder(events)
        builder_b = CaseBuilder(other)

        # interleave work of two concurrent workflow executions
        builder_a._filter_whitelisted("domain", ["schemas.microsoft.com"])
        builder_b._filter_whitelisted("domain", ["ok.test"])
        builder_a._filter_whitelisted("domain", ["www.w3.org"])  # also whitelisted

        assert [message for _, message in events.events] == [
            "Skipped whitelisted domain: schemas.microsoft.com",
            "Skipped whitelisted domain: www.w3.org",
        ]
        assert other.events == []

    def test_simultaneous_analysis_loggers_use_separate_logs(self, fake_redis):
        tracking.create_analysis("analysis-a", 1)
        tracking.create_analysis("analysis-b", 2)
        logger_a = tracking.AnalysisLogger("analysis-a")
        logger_b = tracking.AnalysisLogger("analysis-b")

        logger_a.info("first of a")
        logger_b.info("first of b")
        logger_a.warning("second of a")

        assert [entry["message"] for entry in logger_a.entries] == ["first of a", "second of a"]
        assert [entry["message"] for entry in logger_b.entries] == ["first of b"]
        # the persisted per-analysis logs stay separate as well
        assert [entry["message"] for entry in tracking.get_analysis_log("analysis-a")] == ["first of a", "second of a"]
        assert [entry["message"] for entry in tracking.get_analysis_log("analysis-b")] == ["first of b"]


class TestTranscriptSnapshot:
    def test_snapshot_is_a_point_in_time_copy(self, fake_redis):
        alogger = tracking.AnalysisLogger("analysis-a")
        alogger.info("before snapshot")

        snapshot = alogger.snapshot()
        alogger.info("after snapshot")

        assert [entry["message"] for entry in snapshot] == ["before snapshot"]
        snapshot.clear()  # mutating the snapshot never affects the logger
        assert [entry["message"] for entry in alogger.entries] == ["before snapshot", "after snapshot"]

    def test_snapshot_keeps_entries_that_missed_redis(self, fake_redis):
        fake_redis.fail_on.add("rpush")
        alogger = tracking.AnalysisLogger("analysis-a")
        alogger.info("memory only entry")

        assert [entry["message"] for entry in alogger.snapshot()] == ["memory only entry"]

    def test_result_email_uses_the_explicit_transcript(self, monkeypatch, events):
        stub = ResponderStub(monkeypatch, [MAILER])
        transcript = [
            {"timestamp": "2026-07-23T10:00:00.000+00:00", "level": "info", "message": "step one"},
            {"timestamp": "2026-07-23T10:00:01.000+00:00", "level": "warning", "message": "step two"},
        ]

        Notifier(events).send_analysis_result(BUILT, "user@example.com", "aid123", AnalysisOutcome(verdict="Safe", summary_lines=[]), transcript)

        body = stub.task_updates[0][1]["description"]
        assert "step one" in body and "step two" in body
        assert events.events == [("info", "Sent the result email via Mailer_1_0")]
