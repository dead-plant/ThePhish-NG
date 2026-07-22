"""Tests for analyzer selection, job handling, verdicts and summaries."""

import time

import pytest

from app.repositories import thehive
from app.services.analysis import analyzers, tracking
from app.services.analysis.case_builder import ANALYSIS_TASK, EML_SAMPLE_TAG, SENDER_DOMAIN_TAG, BuiltCase

BUILT = BuiltCase(case={"_id": "case1", "number": 1, "title": "[ThePhish] subject"}, task_ids={ANALYSIS_TASK: "task-analysis"})


def observable(obs_id, data_type, data=None, tags=(), attachment=None):
    obs = {"_id": obs_id, "dataType": data_type, "tags": list(tags)}
    if data is not None:
        obs["data"] = data
    if attachment is not None:
        obs["attachment"] = attachment
    return obs


def analyzer(name):
    return {"id": f"id-{name}", "name": name}


class TheHiveStub:
    """Replace the thehive repository functions used by the analyzer stage."""

    def __init__(
        self,
        monkeypatch,
        observables,
        catalog,
        *,
        levels=None,
        job_reports=None,
        bulk_error=None,
        fail_single=(),
        job_statuses=None,
    ):
        self.observables = observables
        self.catalog = catalog
        self.levels = levels or {}  # analyzer name -> taxonomy level
        self.job_reports = job_reports or {}
        self.bulk_error = bulk_error
        self.fail_single = set(fail_single)
        self.job_statuses = job_statuses or {}  # analyzer name -> job status
        self.jobs = {}  # job id -> (analyzer name, artifact id)
        self.bulk_calls = []
        self.single_calls = []
        self.observable_gets = []
        self.ioc_updates = []
        self._counter = 0

        monkeypatch.setattr(thehive, "update_task", lambda task_id, **kwargs: None)
        monkeypatch.setattr(thehive, "update_case", lambda case_id, **kwargs: None)
        monkeypatch.setattr(thehive, "find_all_observables", lambda case_id: self.observables)
        monkeypatch.setattr(thehive, "list_analyzers_by_type", lambda data_type: self.catalog.get(data_type, []))
        monkeypatch.setattr(thehive, "bulk_create_analyzer_jobs", self._bulk)
        monkeypatch.setattr(thehive, "create_analyzer_job", self._single)
        monkeypatch.setattr(thehive, "get_analyzer_job", self._get_job)
        monkeypatch.setattr(thehive, "get_observable", self._get_observable)
        monkeypatch.setattr(thehive, "bulk_update_observables", lambda ids, *, ioc: self.ioc_updates.append((ids, ioc)))
        monkeypatch.setattr(time, "sleep", lambda seconds: None)

    def _new_job(self, job):
        self._counter += 1
        job_id = f"job-{self._counter}"
        self.jobs[job_id] = (job["analyzer_id"].removeprefix("id-"), job["artifact_id"])
        return {"_id": job_id}

    def _bulk(self, cortex_id, jobs):
        if self.bulk_error is not None:
            raise self.bulk_error
        self.bulk_calls.append((cortex_id, list(jobs)))
        return [self._new_job(job) for job in jobs]

    def _single(self, cortex_id, job):
        analyzer_name = job["analyzer_id"].removeprefix("id-")
        if analyzer_name in self.fail_single:
            raise thehive.TheHiveApiError(f"cannot start {analyzer_name}")
        self.single_calls.append((cortex_id, job))
        return self._new_job(job)

    def _get_job(self, job_id):
        analyzer_name, _ = self.jobs[job_id]
        status = self.job_statuses.get(analyzer_name, "Success")
        job = {"_id": job_id, "status": status, "analyzerName": analyzer_name}
        if status == "Success":
            job["report"] = self.job_reports.get(analyzer_name, {"artifacts": [], "full": {}, "success": True})
        return job

    def _get_observable(self, observable_id):
        self.observable_gets.append(observable_id)
        original = next(item for item in self.observables if item["_id"] == observable_id)
        reports = {
            analyzer_name: {"taxonomies": [{"level": self.levels.get(analyzer_name, "info")}]}
            for analyzer_name, artifact_id in self.jobs.values()
            if artifact_id == observable_id and self.job_statuses.get(analyzer_name, "Success") == "Success"
        }
        return {**original, "reports": reports}

    def started_pairs(self):
        return sorted(self.jobs.values())


@pytest.fixture()
def alogger(fake_redis):
    return tracking.AnalysisLogger("test-analysis")


class TestAnalyzerSelection:
    def test_blacklisted_prefixes_are_skipped(self, monkeypatch, alogger):
        stub = TheHiveStub(
            monkeypatch,
            [observable("o1", "url", data="http://x.test/a")],
            {"url": [analyzer("UnshortenLink_1_2"), analyzer("MSDefenderOffice365_SafeLinksDecoder_json_1_0"), analyzer("SomeUrlAnalyzer_1_0")]},
        )
        analyzers.run_analyzers(BUILT, alogger)
        assert stub.started_pairs() == [("SomeUrlAnalyzer_1_0", "o1")]
        assert any("blacklisted" in entry["message"] for entry in alogger.entries)

    def test_spf_dmarc_runs_only_on_sender_domain(self, monkeypatch, alogger):
        stub = TheHiveStub(
            monkeypatch,
            [
                observable("d1", "domain", data="sender.test", tags=["email", SENDER_DOMAIN_TAG]),
                observable("d2", "domain", data="other.test", tags=["email"]),
            ],
            {"domain": [analyzer("DomainMailSPFDMARC_1_2"), analyzer("DomainWatcher_1_0")]},
        )
        analyzers.run_analyzers(BUILT, alogger)
        assert stub.started_pairs() == [
            ("DomainMailSPFDMARC_1_2", "d1"),
            ("DomainWatcher_1_0", "d1"),
            ("DomainWatcher_1_0", "d2"),
        ]

    def test_only_yara_runs_on_the_eml_file(self, monkeypatch, alogger):
        stub = TheHiveStub(
            monkeypatch,
            [
                observable("f1", "file", tags=["email", EML_SAMPLE_TAG], attachment={"name": "mail.eml", "contentType": "application/octet-stream"}),
                observable("f2", "file", tags=["email", "email_attachment"], attachment={"name": "doc.pdf", "contentType": "application/pdf"}),
            ],
            {"file": [analyzer("Yara_3_0"), analyzer("FileInfo_8_0")]},
        )
        analyzers.run_analyzers(BUILT, alogger)
        assert stub.started_pairs() == [
            ("FileInfo_8_0", "f2"),
            ("Yara_3_0", "f1"),
            ("Yara_3_0", "f2"),
        ]


class TestJobHandling:
    def test_jobs_are_created_in_bulk(self, monkeypatch, alogger):
        stub = TheHiveStub(
            monkeypatch,
            [observable("d1", "domain", data="a.test"), observable("d2", "domain", data="b.test")],
            {"domain": [analyzer("DomainWatcher_1_0")]},
        )
        analyzers.run_analyzers(BUILT, alogger)
        assert len(stub.bulk_calls) == 1
        assert stub.single_calls == []
        assert len(stub.jobs) == 2

    def test_successful_jobs_refresh_an_observable_once(self, monkeypatch, alogger):
        stub = TheHiveStub(
            monkeypatch,
            [observable("d1", "domain", data="odd.test")],
            {"domain": [analyzer("First_1_0"), analyzer("Second_1_0")]},
            levels={"First_1_0": "suspicious", "Second_1_0": "info"},
        )

        outcome = analyzers.run_analyzers(BUILT, alogger)

        assert outcome.verdict == "Suspicious"
        assert stub.observable_gets == ["d1"]

    def test_fallback_to_individual_jobs(self, monkeypatch, alogger):
        stub = TheHiveStub(
            monkeypatch,
            [observable("d1", "domain", data="a.test")],
            {"domain": [analyzer("GoodAnalyzer_1_0"), analyzer("BadAnalyzer_1_0")]},
            bulk_error=thehive.TheHiveApiError("bulk endpoint not found"),
            fail_single={"BadAnalyzer_1_0"},
        )
        outcome = analyzers.run_analyzers(BUILT, alogger)
        # the failed analyzer does not prevent the other one from running
        assert stub.started_pairs() == [("GoodAnalyzer_1_0", "d1")]
        assert any("could not be started" in line for line in outcome.summary_lines)
        assert "Analyzer reports: 1 collected, 1 failed" in outcome.summary_lines

    def test_timed_out_jobs_are_reported(self, monkeypatch, alogger):
        monkeypatch.setattr(analyzers, "JOB_TIMEOUT", 0.05)
        monkeypatch.setattr(analyzers, "POLL_INTERVAL", 0.0)
        TheHiveStub(
            monkeypatch,
            [observable("d1", "domain", data="a.test")],
            {"domain": [analyzer("SlowAnalyzer_1_0")]},
            job_statuses={"SlowAnalyzer_1_0": "InProgress"},
        )
        outcome = analyzers.run_analyzers(BUILT, alogger)
        assert outcome.verdict == "Safe"
        assert any("timed out" in line for line in outcome.summary_lines)

    def test_failed_jobs_are_reported(self, monkeypatch, alogger):
        TheHiveStub(
            monkeypatch,
            [observable("d1", "domain", data="a.test")],
            {"domain": [analyzer("FailingAnalyzer_1_0")]},
            job_statuses={"FailingAnalyzer_1_0": "Failure"},
        )
        outcome = analyzers.run_analyzers(BUILT, alogger)
        assert any("job failed" in line for line in outcome.summary_lines)
        assert any(entry["level"] == "warning" and "FailingAnalyzer_1_0" in entry["message"] for entry in alogger.entries)


class TestVerdict:
    def test_malicious_report_marks_ioc_and_verdict(self, monkeypatch, alogger):
        stub = TheHiveStub(
            monkeypatch,
            [observable("d1", "domain", data="evil.test")],
            {"domain": [analyzer("MalwareFinder_1_0")]},
            levels={"MalwareFinder_1_0": "malicious"},
        )
        outcome = analyzers.run_analyzers(BUILT, alogger)
        assert outcome.verdict == "Malicious"
        assert stub.ioc_updates == [(["d1"], True)]
        assert "Malicious: MalwareFinder_1_0 on domain evil.test" in outcome.summary_lines

    def test_job_without_taxonomies_uses_observable_report(self, monkeypatch, alogger):
        stub = TheHiveStub(
            monkeypatch,
            [observable("d1", "domain", data="evil.test")],
            {"domain": [analyzer("MalwareFinder_1_0")]},
            levels={"MalwareFinder_1_0": "malicious"},
            job_reports={"MalwareFinder_1_0": {"artifacts": [], "full": {}, "success": True}},
        )

        outcome = analyzers.run_analyzers(BUILT, alogger)

        assert outcome.verdict == "Malicious"
        assert stub.ioc_updates == [(["d1"], True)]

    def test_suspicious_report_gives_suspicious_verdict(self, monkeypatch, alogger):
        stub = TheHiveStub(
            monkeypatch,
            [observable("d1", "domain", data="odd.test")],
            {"domain": [analyzer("MalwareFinder_1_0")]},
            levels={"MalwareFinder_1_0": "suspicious"},
        )
        outcome = analyzers.run_analyzers(BUILT, alogger)
        assert outcome.verdict == "Suspicious"
        assert stub.ioc_updates == []
        assert "Suspicious: MalwareFinder_1_0 on domain odd.test" in outcome.summary_lines

    def test_info_reports_give_safe_verdict(self, monkeypatch, alogger):
        TheHiveStub(
            monkeypatch,
            [observable("d1", "domain", data="fine.test")],
            {"domain": [analyzer("MalwareFinder_1_0")]},
        )
        outcome = analyzers.run_analyzers(BUILT, alogger)
        assert outcome.verdict == "Safe"
        assert outcome.summary_lines[0] == "Analyzer reports: 1 collected, 0 failed"


class TestLevelResolution:
    @pytest.fixture(autouse=True)
    def identity_mapping(self, monkeypatch):
        # keep the configured level mappings out of these quirk tests
        monkeypatch.setattr(analyzers.analyzer_level_mappings, "map_level", lambda name, obs_type, level: level)

    def test_default_uses_first_taxonomy(self):
        job = {"analyzerName": "SomeAnalyzer_1_0", "report": {}}
        report = {"taxonomies": [{"level": "suspicious"}, {"level": "malicious"}]}
        assert analyzers._resolve_level(job, "domain", report) == "suspicious"

    def test_last_taxonomy_analyzers(self):
        job = {"analyzerName": "Pulsedive_GetIndicator_1_0", "report": {}}
        report = {"taxonomies": [{"level": "info"}, {"level": "malicious"}]}
        assert analyzers._resolve_level(job, "domain", report) == "malicious"

    def test_spamhaus_return_codes(self):
        job = {"analyzerName": "SpamhausDBL_1_0", "report": {}}
        assert analyzers._resolve_level(job, "domain", {"taxonomies": [{"value": "127.0.1.2"}]}) == "malicious"
        assert analyzers._resolve_level(job, "domain", {"taxonomies": [{"value": "NXDOMAIN"}]}) == "info"

    def test_urlhaus_threat_in_full_report(self):
        job = {"analyzerName": "URLhaus_2_0", "report": {"full": {"query_status": "ok", "threat": "malware_download"}}}
        assert analyzers._resolve_level(job, "url", {"taxonomies": [{"level": "info"}]}) == "malicious"

    def test_missing_taxonomies_default_to_info(self):
        job = {"analyzerName": "SomeAnalyzer_1_0", "report": {}}
        assert analyzers._resolve_level(job, "domain", {}) == "info"

    def test_urlhaus_full_report_shape_variants(self):
        for report in (
            {"full": {"query_status": "ok", "threat": "malware_download"}},
            {"report": {"full": {"query_status": "ok", "threat": "malware_download"}}},
        ):
            job = {"analyzerName": "URLhaus_2_0", "report": report}
            assert analyzers._resolve_level(job, "url", {"taxonomies": [{"level": "info"}]}) == "malicious"


def test_configured_level_mapping_is_applied():
    # config-example maps malicious -> suspicious for this analyzer on domains
    job = {"analyzerName": "DomainMailSPFDMARC_Analyzer_1_2", "report": {}}
    assert analyzers._resolve_level(job, "domain", {"taxonomies": [{"level": "malicious"}]}) == "suspicious"
