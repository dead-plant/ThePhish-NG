"""Tests for mail responder selection, directives and the result email."""

import re
import time

import pytest

from app.repositories import thehive
from app.services.analysis import notifications, tracking
from app.services.analysis.analyzers import AnalysisOutcome
from app.services.analysis.case_builder import NOTIFICATION_TASK, RESULT_TASK, BuiltCase

BUILT = BuiltCase(
    case={"_id": "case1", "number": 1, "title": "[ThePhish] Suspicious invoice"},
    task_ids={NOTIFICATION_TASK: "task-notif", RESULT_TASK: "task-result"},
)
PHISHMAILER = {"id": "id-phishmailer", "name": "PhishMailer_1_0"}
MAILER = {"id": "id-mailer", "name": "Mailer_1_0"}


class ResponderStub:
    """Replace the thehive repository functions used by the notification stage."""

    def __init__(self, monkeypatch, responders, *, action_status="Success", update_error=None):
        self.responders = responders
        self.action_status = action_status
        self.update_error = update_error
        self.task_updates = []
        self.actions = []

        monkeypatch.setattr(thehive, "list_responders_for_entity", lambda entity_type, entity_id: self.responders)
        monkeypatch.setattr(thehive, "update_task", self._update_task)
        monkeypatch.setattr(thehive, "create_responder_action", self._create_action)
        monkeypatch.setattr(thehive, "get_responder_action", lambda entity_type, entity_id: {"status": self.action_status})
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

    def _update_task(self, task_id, **kwargs):
        if self.update_error is not None:
            raise self.update_error
        self.task_updates.append((task_id, kwargs))

    def _create_action(self, **kwargs):
        self.actions.append(kwargs)
        return {"_id": "action1", "status": "Waiting", **kwargs}


@pytest.fixture()
def alogger(fake_redis):
    return tracking.AnalysisLogger("test-analysis")


@pytest.fixture()
def notifier(alogger):
    return notifications.Notifier(alogger)


class TestResponderSelection:
    def test_phishmailer_is_preferred(self, monkeypatch, notifier, alogger):
        stub = ResponderStub(monkeypatch, [MAILER, PHISHMAILER])
        notifier.send_analysis_started(BUILT, "user@example.com")

        assert stub.actions == [{"responder_id": "id-phishmailer", "object_type": "case_task", "object_id": "task-notif"}]
        directive = stub.task_updates[0][1]["description"].splitlines()[0]
        assert re.fullmatch(r'#PhishMailer; subject: "[^"]+"; mailto:user@example\.com;', directive)
        assert stub.task_updates[-1] == ("task-notif", {"status": "Completed"})
        assert any("Sent the notification email via PhishMailer_1_0" == entry["message"] for entry in alogger.entries)

    def test_fallback_to_standard_mailer(self, monkeypatch, notifier, alogger):
        stub = ResponderStub(monkeypatch, [MAILER])
        notifier.send_analysis_started(BUILT, "user@example.com")

        assert stub.actions[0]["responder_id"] == "id-mailer"
        description = stub.task_updates[0][1]["description"]
        assert description.startswith("mailto:user@example.com\n")
        assert "#PhishMailer" not in description

    def test_no_responder_available(self, monkeypatch, notifier, alogger):
        stub = ResponderStub(monkeypatch, [])
        notifier.send_analysis_started(BUILT, "user@example.com")

        assert stub.actions == []
        assert any(entry["level"] == "warning" and "no mail responder" in entry["message"] for entry in alogger.entries)


class TestInputSafety:
    def test_recipient_is_normalized_without_deliverability_check(self, monkeypatch, notifier, alogger):
        stub = ResponderStub(monkeypatch, [PHISHMAILER])

        notifier.send_analysis_started(BUILT, "User@NONEXISTENT-DOMAIN-7F9CC67.COM")

        directive = stub.task_updates[0][1]["description"].splitlines()[0]
        assert "mailto:User@nonexistent-domain-7f9cc67.com;" in directive

    @pytest.mark.parametrize("recipient", [
        "with space@example.com",
        'quote"y@example.com',
        "semi;colon@example.com",
        "line\nbreak@example.com",
        "angle<b>@example.com",
        "comma,x@example.com",
        "noat.example.com",
        "a@b",
        "",
    ])
    def test_unsafe_recipients_are_rejected(self, monkeypatch, notifier, alogger, recipient):
        stub = ResponderStub(monkeypatch, [PHISHMAILER])
        notifier.send_analysis_started(BUILT, recipient)

        assert stub.task_updates == [] and stub.actions == []
        assert any("not a safe email address" in entry["message"] for entry in alogger.entries)

    def test_subject_sanitization(self):
        subject = notifications._sanitize_subject('bad "subject"\r\nwith\tcontrol\x00chars ' + "x" * 200)
        assert '"' not in subject
        assert not re.search(r"[\x00-\x1f\x7f]", subject)
        assert len(subject) <= 120

    def test_subject_urls_are_defanged(self):
        subject = notifications._sanitize_subject("ThePhish verdict: Malicious [visit http://evil.example.com now]")
        assert "http://evil.example.com" not in subject
        assert "hXXp://evil[.]example[.]com" in subject

    def test_directive_stays_intact_with_hostile_case_title(self, monkeypatch, notifier, alogger):
        stub = ResponderStub(monkeypatch, [PHISHMAILER])
        built = BuiltCase(case={"_id": "c", "number": 2, "title": '[ThePhish] evil"; mailto:attacker@evil.test;'}, task_ids=BUILT.task_ids)
        notifier.send_analysis_started(built, "user@example.com")

        directive = stub.task_updates[0][1]["description"].splitlines()[0]
        assert re.fullmatch(r'#PhishMailer; subject: "[^"]+"; mailto:user@example\.com;', directive)


class TestResultEmail:
    def test_result_email_contains_link_verdict_summary_and_log(self, monkeypatch, notifier, alogger):
        stub = ResponderStub(monkeypatch, [PHISHMAILER])
        alogger.info("step one")
        alogger.warning("step two")
        outcome = AnalysisOutcome(verdict="Malicious", summary_lines=["Analyzer reports: 3 collected, 1 failed", "Malicious: X on domain evil.test"])

        notifier.send_analysis_result(BUILT, "user@example.com", "aid123", outcome, alogger.snapshot())

        body = stub.task_updates[0][1]["description"]
        lines = body.splitlines()
        # the placeholder link sits at the top of the email body (below the directive line)
        assert lines[1] == "https://thephish.example.com/analysis/aid123"
        assert "Final verdict: Malicious" in lines
        assert "Analyzer reports: 3 collected, 1 failed" in lines
        assert "Malicious: X on domain evil[.]test" in lines  # summary lines are defanged
        assert any("step one" in line for line in lines)
        assert any("step two" in line for line in lines)
        assert stub.actions[0]["object_id"] == "task-result"
        assert stub.task_updates[-1] == ("task-result", {"status": "Completed"})

    def test_result_email_contains_no_clickable_iocs(self, monkeypatch, notifier, alogger):
        stub = ResponderStub(monkeypatch, [PHISHMAILER])
        alogger.info("Found observable url: http://evil.example.com/login")
        outcome = AnalysisOutcome(verdict="Malicious", summary_lines=["Malicious: URLhaus_2_0 on url http://bad.example.org/x"])

        notifier.send_analysis_result(BUILT, "user@example.com", "aid123", outcome, alogger.snapshot())

        body = stub.task_updates[0][1]["description"]
        # the analysis link at the top is the only clickable URL in the email
        assert "http://evil.example.com" not in body
        assert "http://bad.example.org" not in body
        assert "hXXp://evil[.]example[.]com/login" in body
        assert "hXXp://bad[.]example[.]org/x" in body
        assert body.count("https://") == 1  # only https://thephish.example.com/analysis/aid123

    def test_result_email_keeps_log_entries_that_missed_redis(self, monkeypatch, notifier, alogger, fake_redis):
        stub = ResponderStub(monkeypatch, [MAILER])
        fake_redis.fail_on.add("rpush")
        alogger.info("memory only entry")
        outcome = AnalysisOutcome(verdict="Safe", summary_lines=[])

        notifier.send_analysis_result(BUILT, "user@example.com", "aid123", outcome, alogger.snapshot())

        assert "memory only entry" in stub.task_updates[0][1]["description"]


class TestFailureHandling:
    def test_responder_failure_is_a_warning(self, monkeypatch, notifier, alogger):
        stub = ResponderStub(monkeypatch, [PHISHMAILER], action_status="Failure")
        notifier.send_analysis_started(BUILT, "user@example.com")

        assert any("could not be delivered" in entry["message"] for entry in alogger.entries)
        assert stub.task_updates[-1] == ("task-notif", {"status": "Completed"})

    def test_thehive_error_does_not_raise(self, monkeypatch, notifier, alogger):
        ResponderStub(monkeypatch, [PHISHMAILER], update_error=thehive.TheHiveApiError("api down"))
        notifier.send_analysis_result(BUILT, "user@example.com", "aid123", AnalysisOutcome(verdict="Safe", summary_lines=[]), alogger.snapshot())

        assert any(entry["level"] == "warning" and "result email" in entry["message"] for entry in alogger.entries)

    def test_missing_task_is_a_warning(self, monkeypatch, notifier, alogger):
        stub = ResponderStub(monkeypatch, [PHISHMAILER])
        built = BuiltCase(case=BUILT.case, task_ids={})
        notifier.send_analysis_started(built, "user@example.com")

        assert stub.actions == []
        assert any("the case task is missing" in entry["message"] for entry in alogger.entries)
