"""Tests for case building: sender domain, filtering, URL expansion, TheHive calls."""

import email
import os
from email.message import EmailMessage

import pytest

from app.repositories import thehive
from app.services.analysis import case_builder, tracking
from app.services.analysis.case_builder import ANALYSIS_TASK, NOTIFICATION_TASK, RESULT_TASK, SENDER_DOMAIN_TAG
from app.services.analysis.errors import AnalysisError


def make_eml() -> EmailMessage:
    # ioc_finder only extracts domains with valid public TLDs, so the test data uses .com
    msg = EmailMessage()
    msg["From"] = "Bad Guy <bad.guy@evil-sender.com>"
    msg["To"] = "victim@corp.com"
    msg["Subject"] = "Attack invoice"
    msg.set_content("Visit http://phish.example.com/login now")
    msg.add_attachment(b"%PDF-1.4 fake content", maintype="application", subtype="pdf", filename="invoice.pdf")
    return msg


class CaseStub:
    """Replace the thehive repository functions used by the case builder."""

    def __init__(self, monkeypatch, *, create_error=None, observable_error_types=()):
        self.create_error = create_error
        self.observable_error_types = set(observable_error_types)
        self.case = {"_id": "case1", "number": 7, "title": "[ThePhish] Attack invoice"}
        self.observables = []  # (data_type, data, tags, message)
        self.files = []  # (basename, tags)

        monkeypatch.setattr(thehive, "create_case_template_unless_exists", lambda **kwargs: {"_id": "template1"})
        monkeypatch.setattr(thehive, "create_case", self._create_case)
        monkeypatch.setattr(thehive, "create_observable", self._create_observable)
        monkeypatch.setattr(thehive, "create_file_observable", self._create_file_observable)
        monkeypatch.setattr(thehive, "find_all_tasks", lambda case_id: [
            {"title": NOTIFICATION_TASK, "_id": "t1"},
            {"title": ANALYSIS_TASK, "_id": "t2"},
            {"title": RESULT_TASK, "_id": "t3"},
        ])
        # no real network requests during URL expansion
        monkeypatch.setattr(case_builder.redirect_tracker, "get_trace", lambda url: [])

    def _create_case(self, **kwargs):
        if self.create_error is not None:
            raise self.create_error
        self.case_kwargs = kwargs
        return self.case

    def _create_observable(self, *, case_id, data_type, data, ioc=False, tags=None, message=""):
        if data_type in self.observable_error_types:
            raise thehive.TheHiveApiError(f"cannot add {data_type}")
        self.observables.append((data_type, list(data), list(tags or []), message))
        return [{"_id": f"obs-{len(self.observables)}"}]

    def _create_file_observable(self, *, case_id, file_path, ioc=False, tags=None, message="", is_zip=False):
        assert os.path.isfile(file_path)
        self.files.append((os.path.basename(file_path), list(tags or [])))
        return {"_id": f"file-{len(self.files)}"}

    def observables_of_type(self, data_type):
        return [entry for entry in self.observables if entry[0] == data_type]


@pytest.fixture()
def alogger(fake_redis):
    return tracking.AnalysisLogger("test-analysis")


@pytest.fixture()
def builder(alogger):
    return case_builder.CaseBuilder(alogger)


class TestSenderDomain:
    @pytest.mark.parametrize("from_header,expected", [
        ("user@Example.COM", "example.com"),
        ("Bad Guy <bad@evil.test>", "evil.test"),
        ("bad@evil.test.", "evil.test"),
        ("not an address", None),
        ("", None),
    ])
    def test_sender_domain_extraction(self, from_header, expected):
        # parse from raw text (compat32), like emails fetched from the mailbox
        msg = email.message_from_string(f"From: {from_header}\n\nbody" if from_header else "\nbody")
        assert case_builder.sender_domain(msg) == expected


class TestFilteringAndUrls:
    def test_whitelisted_values_are_dropped(self, builder, alogger):
        # schemas.microsoft.com is whitelisted in config-example/whitelist.json
        kept = builder._filter_whitelisted("domain", ["schemas.microsoft.com", "ok.test"])
        assert kept == ["ok.test"]
        assert any("whitelisted" in entry["message"] for entry in alogger.entries)

    def test_empty_values_are_dropped(self, builder):
        assert builder._filter_whitelisted("domain", ["", "  ", "ok.test"]) == ["ok.test"]

    def test_safelinks_are_decoded(self, monkeypatch, builder):
        monkeypatch.setattr(case_builder.redirect_tracker, "get_trace", lambda url: [])
        safelink = "https://eur01.safelinks.protection.outlook.com/?url=http%3A%2F%2Ftarget.test%2Fpage"
        groups = builder._collect_urls([safelink])
        assert groups["url"] == [safelink]
        assert groups["safelink_decoded"] == ["http://target.test/page"]

    def test_redirects_are_expanded_and_failures_recoverable(self, monkeypatch, builder, alogger):
        def get_trace(url):
            if url == "http://short.test/a":
                return ["http://landing.test/final"]
            raise case_builder.RedirectTrackerError("connection refused")

        monkeypatch.setattr(case_builder.redirect_tracker, "get_trace", get_trace)
        groups = builder._collect_urls(["http://short.test/a", "http://broken.test/b"])
        assert groups["redirect_target"] == ["http://landing.test/final"]
        # the log entry exists, defanged so the broken URL is not clickable
        assert any("Could not follow redirects of hXXp://broken[.]test/b" in entry["message"] for entry in alogger.entries)


class TestBuildCase:
    def test_happy_path_populates_the_case(self, monkeypatch, builder):
        stub = CaseStub(monkeypatch)
        built = builder.build_case(make_eml())

        assert built.case is stub.case
        assert built.task_ids == {NOTIFICATION_TASK: "t1", ANALYSIS_TASK: "t2", RESULT_TASK: "t3"}
        assert stub.case_kwargs["title"] == "Attack invoice"
        assert stub.case_kwargs["template"] == "ThePhish"

        # the sender domain is tagged so the SPF/DMARC analyzer can find it
        sender_batches = [entry for entry in stub.observables_of_type("domain") if SENDER_DOMAIN_TAG in entry[2]]
        assert len(sender_batches) == 1 and sender_batches[0][1] == ["evil-sender.com"]
        # and it is not duplicated in the generic domain batch
        generic_domains = [value for entry in stub.observables_of_type("domain") if SENDER_DOMAIN_TAG not in entry[2] for value in entry[1]]
        assert "evil-sender.com" not in generic_domains and "phish.example.com" in generic_domains

        assert ["http://phish.example.com/login"] in [entry[1] for entry in stub.observables_of_type("url")]
        assert any("bad.guy@evil-sender.com" in entry[1] for entry in stub.observables_of_type("mail"))
        assert ["Attack invoice"] in [entry[1] for entry in stub.observables_of_type("mail-subject")]
        assert stub.observables_of_type("hash")  # sha256 of the attachment

        file_names = {name for name, _ in stub.files}
        assert file_names == {"invoice.pdf", "Attack invoice.eml"}
        eml_tags = next(tags for name, tags in stub.files if name.endswith(".eml"))
        assert case_builder.EML_SAMPLE_TAG in eml_tags

    def test_case_creation_failure_is_fatal(self, monkeypatch, builder):
        CaseStub(monkeypatch, create_error=thehive.TheHiveApiError("api down"))
        with pytest.raises(AnalysisError):
            builder.build_case(make_eml())

    def test_single_observable_failure_is_recoverable(self, monkeypatch, builder, alogger):
        stub = CaseStub(monkeypatch, observable_error_types={"url"})
        built = builder.build_case(make_eml())

        assert built.case is stub.case
        assert any(entry["level"] == "warning" and "url" in entry["message"] for entry in alogger.entries)
        assert stub.observables_of_type("mail")  # other observables were still added

    def test_whitelisted_attachment_is_skipped(self, monkeypatch, builder, alogger):
        stub = CaseStub(monkeypatch)
        monkeypatch.setattr(case_builder.whitelist, "is_whitelisted", lambda obs_type, value: obs_type == "filename" and value == "invoice.pdf")
        builder.build_case(make_eml())

        file_names = {name for name, _ in stub.files}
        assert "invoice.pdf" not in file_names
        assert any(entry["message"].startswith("Skipped whitelisted attachment: invoice") for entry in alogger.entries)


class TestFinalizeCase:
    def test_malicious_verdict_exports_and_closes(self, monkeypatch, builder, alogger):
        calls = []
        monkeypatch.setattr(thehive, "export_case", lambda case_id, misp_id: calls.append(("export", case_id, misp_id)))
        monkeypatch.setattr(thehive, "close_case", lambda *, case_id, status, summary, impact_status: calls.append(("close", case_id, status)))
        built = case_builder.BuiltCase(case={"_id": "case1", "number": 7, "title": "[ThePhish] x"}, task_ids={})

        builder.finalize_case(built, "Malicious")
        assert calls == [("export", "case1", "MISP"), ("close", "case1", "TruePositive")]

    def test_safe_verdict_closes_as_false_positive(self, monkeypatch, builder, alogger):
        calls = []
        monkeypatch.setattr(thehive, "export_case", lambda case_id, misp_id: calls.append("export"))
        monkeypatch.setattr(thehive, "close_case", lambda *, case_id, status, summary, impact_status: calls.append(("close", status)))
        built = case_builder.BuiltCase(case={"_id": "case1", "number": 7, "title": "[ThePhish] x"}, task_ids={})

        builder.finalize_case(built, "Safe")
        assert calls == [("close", "FalsePositive")]

    def test_suspicious_verdict_leaves_case_open(self, monkeypatch, builder, alogger):
        monkeypatch.setattr(thehive, "close_case", lambda **kwargs: pytest.fail("case must stay open"))
        built = case_builder.BuiltCase(case={"_id": "case1", "number": 7, "title": "[ThePhish] x"}, task_ids={})

        builder.finalize_case(built, "Suspicious")
        assert any("stays open" in entry["message"] for entry in alogger.entries)

    def test_export_failure_is_recoverable(self, monkeypatch, builder, alogger):
        def export_error(case_id, misp_id):
            raise thehive.TheHiveApiError("misp down")

        closed = []
        monkeypatch.setattr(thehive, "export_case", export_error)
        monkeypatch.setattr(thehive, "close_case", lambda **kwargs: closed.append(kwargs))
        built = case_builder.BuiltCase(case={"_id": "case1", "number": 7, "title": "[ThePhish] x"}, task_ids={})

        builder.finalize_case(built, "Malicious")
        assert closed and closed[0]["status"] == "TruePositive"
        assert any("Could not export" in entry["message"] for entry in alogger.entries)
