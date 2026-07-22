"""Running Cortex analyzers on the case observables and computing the verdict.

Discovers the applicable analyzers per observable type, starts the jobs (bulk
with an individual-job fallback for older TheHive versions), polls them until
completion or timeout, resolves the result levels and derives the verdict.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Final, Optional

from thehive4py.types.cortex import OutputAnalyzer, OutputAnalyzerJob

from app import config
from app.repositories import thehive
from app.repositories.thehive import TheHiveApiError
from app.services.analysis.case_builder import ANALYSIS_TASK, EML_SAMPLE_TAG, SENDER_DOMAIN_TAG, BuiltCase
from app.services.analysis.errors import AnalysisError
from app.services.analysis.tracking import AnalysisLogger
from app.utils import analyzer_level_mappings

log = logging.getLogger(__name__)

VERDICT_MALICIOUS: Final = "Malicious"
VERDICT_SUSPICIOUS: Final = "Suspicious"
VERDICT_SAFE: Final = "Safe"

# Only analyzers with this prefix run on the attached EML file observable.
_EML_ANALYZER_PREFIX: Final = "Yara"
# The SPF/DMARC analyzer only makes sense for the sender's domain.
_SPF_DMARC_ANALYZER_PREFIX: Final = "DomainMailSPFDMARC"

POLL_INTERVAL: Final[float] = 5.0  # seconds between job status polls
JOB_TIMEOUT: Final[float] = 900.0  # seconds before pending jobs are given up

_TERMINAL_JOB_STATUSES: Final = ("Success", "Failure")

# SpamhausDBL return codes that indicate a malicious domain.
_SPAMHAUS_MALICIOUS_CODES: Final = ("127.0.1.2", "127.0.1.4", "127.0.1.5", "127.0.1.6", "127.0.1.102", "127.0.1.103", "127.0.1.104", "127.0.1.105", "127.0.1.106")
# Analyzers that put the relevant taxonomy last instead of first.
_LAST_TAXONOMY_ANALYZERS: Final = ("Pulsedive_GetIndicator_1_0", "IPVoid_1_0", "Shodan_Host_1_0", "Shodan_Host_History_1_0")


@dataclass(frozen=True)
class _ObservableInfo:
    observable_id: str
    name: str
    data_type: str
    is_eml: bool
    is_sender_domain: bool


@dataclass
class _JobRecord:
    observable: _ObservableInfo
    analyzer_name: str
    analyzer_id: str
    job_id: Optional[str] = None
    status: str = "pending"  # pending -> Success | Failure | failed_to_start | timed_out
    level: Optional[str] = None


@dataclass(frozen=True)
class AnalysisOutcome:
    verdict: str
    summary_lines: list[str] = field(default_factory=list)


def _observable_info(observable: dict) -> _ObservableInfo:
    tags = observable.get("tags", [])
    if observable["dataType"] == "file":
        attachment = observable.get("attachment") or {}
        name = attachment.get("name", "unknown")
        is_eml = EML_SAMPLE_TAG in tags or attachment.get("contentType") == "message/rfc822"
    else:
        name = observable.get("data", "unknown")
        is_eml = False
    return _ObservableInfo(
        observable_id=observable["_id"],
        name=name,
        data_type=observable["dataType"],
        is_eml=is_eml,
        is_sender_domain=SENDER_DOMAIN_TAG in tags,
    )


def _analyzer_catalog(data_types: set[str], alogger: AnalysisLogger) -> dict[str, list[OutputAnalyzer]]:
    """Discover the enabled analyzers for every observable type in the case."""
    catalog: dict[str, list[OutputAnalyzer]] = {}
    for data_type in sorted(data_types):
        try:
            catalog[data_type] = thehive.list_analyzers_by_type(data_type)
        except TheHiveApiError as exc:
            alogger.warning(f"Could not list analyzers for type {data_type}: {exc}")
            catalog[data_type] = []
    return catalog


def _plan_jobs(infos: list[_ObservableInfo], catalog: dict[str, list[OutputAnalyzer]], alogger: AnalysisLogger) -> list[_JobRecord]:
    """Apply the selection rules and build the list of jobs to start."""
    blacklist = tuple(config.get_app_config()["analysis"].get("analyzer_prefix_blacklist", []))
    skipped_blacklisted: set[str] = set()

    records = []
    for info in infos:
        for analyzer in catalog.get(info.data_type, []):
            name = analyzer["name"]
            if blacklist and name.startswith(blacklist):
                skipped_blacklisted.add(name)
                continue
            if info.is_eml and not name.startswith(_EML_ANALYZER_PREFIX):
                continue
            if name.startswith(_SPF_DMARC_ANALYZER_PREFIX) and not (info.data_type == "domain" and info.is_sender_domain):
                continue
            records.append(_JobRecord(observable=info, analyzer_name=name, analyzer_id=analyzer["id"]))

    if skipped_blacklisted:
        alogger.info(f"Skipped blacklisted analyzer(s): {', '.join(sorted(skipped_blacklisted))}")
    return records


def _start_jobs(records: list[_JobRecord], alogger: AnalysisLogger) -> None:
    """Start all planned jobs, preferring bulk creation.

    Falls back to individual job creation when bulk creation is unavailable
    (older TheHive versions) or fails; a single analyzer that cannot be
    started never prevents the others from running.
    """
    if not records:
        return
    cortex_id = config.get_app_config()["thehive"]["cortex_id"]
    jobs = [{"artifact_id": record.observable.observable_id, "analyzer_id": record.analyzer_id} for record in records]

    try:
        created = thehive.bulk_create_analyzer_jobs(cortex_id, jobs)
        if len(created) != len(records):
            raise TheHiveApiError(f"Bulk job creation returned {len(created)} job(s) for {len(records)} request(s)")
        for record, job in zip(records, created):
            record.job_id = job["_id"]
        alogger.info(f"Started {len(records)} analyzer job(s)")
        return
    except (TheHiveApiError, ValueError) as exc:
        log.info("Bulk analyzer job creation failed, falling back to individual jobs (%s)", exc)
        alogger.info("Bulk analyzer job creation is unavailable; starting jobs individually")

    for record, job_input in zip(records, jobs):
        try:
            record.job_id = thehive.create_analyzer_job(cortex_id, job_input)["_id"]
            alogger.info(f"Started analyzer {record.analyzer_name} for {record.observable.data_type} {record.observable.name}")
        except (TheHiveApiError, ValueError) as exc:
            record.status = "failed_to_start"
            alogger.warning(f"Could not start analyzer {record.analyzer_name} for {record.observable.data_type} {record.observable.name}: {exc}")


def _poll_jobs(records: list[_JobRecord], alogger: AnalysisLogger) -> None:
    """Wait for all started jobs to finish, up to the job timeout."""
    pending = [record for record in records if record.job_id is not None]
    if not pending:
        return
    alogger.info(f"Waiting for {len(pending)} analyzer job(s) to complete...")

    completed_jobs: dict[str, OutputAnalyzerJob] = {}
    deadline = time.monotonic() + JOB_TIMEOUT
    errors = 0
    while pending and time.monotonic() < deadline and errors < 5:
        time.sleep(POLL_INTERVAL)
        for record in pending[:]:
            try:
                job = thehive.get_analyzer_job(record.job_id)
            except TheHiveApiError as exc:
                log.debug("Polling analyzer job %s failed (%s)", record.job_id, exc)
                errors += 1
                continue  # transient; bounded by the deadline
            if job.get("status") in _TERMINAL_JOB_STATUSES:
                record.status = job["status"]
                if job["status"] == "Success":
                    completed_jobs[record.job_id] = job
                else:
                    record.level = None
                    _log_job_result(record, alogger)
                pending.remove(record)

    for record in pending:
        record.status = "timed_out"
        alogger.warning(f"Analyzer {record.analyzer_name} for {record.observable.data_type} {record.observable.name} did not finish in time")

    _resolve_successful_levels(records, completed_jobs, alogger)


def _resolve_successful_levels(
    records: list[_JobRecord],
    jobs: dict[str, OutputAnalyzerJob],
    alogger: AnalysisLogger,
) -> None:
    """Resolve successful jobs from one refreshed report snapshot per observable."""
    records_by_observable: dict[str, list[_JobRecord]] = {}
    for record in records:
        if record.status == "Success" and record.job_id is not None and record.job_id in jobs:
            records_by_observable.setdefault(record.observable.observable_id, []).append(record)

    for observable_id, observable_records in records_by_observable.items():
        try:
            reports = thehive.get_observable(observable_id).get("reports") or {}
        except TheHiveApiError as exc:
            log.warning("Could not retrieve analyzer reports for observable %s (%s)", observable_id, exc)
            reports = {}
        if not isinstance(reports, dict):
            reports = {}

        for record in observable_records:
            job = jobs[record.job_id]
            analyzer_name = job.get("analyzerName") or record.analyzer_name
            record.level = _resolve_level(job, record.observable.data_type, reports.get(analyzer_name, {}))
            _log_job_result(record, alogger)


def _log_job_result(record: _JobRecord, alogger: AnalysisLogger) -> None:
    subject = f"{record.analyzer_name} for {record.observable.data_type} {record.observable.name}"
    if record.status == "Success":
        alogger.info(f"Analyzer {subject} finished with level {record.level}")
    else:
        alogger.warning(f"Analyzer {subject} failed")


def _as_dict(value: object) -> dict:
    """Return the value as a dict, decoding JSON strings; {} for anything else."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _extract_taxonomies(observable_report: object) -> list[dict]:
    """Extract taxonomy dictionaries from a TheHive observable report."""
    taxonomies = _as_dict(observable_report).get("taxonomies")
    if not isinstance(taxonomies, list):
        return []
    return [taxonomy for taxonomy in taxonomies if isinstance(taxonomy, dict)]


def _extract_full_report(job_report: object) -> dict:
    """Extract the full report section, tolerating the same shape variants."""
    report = _as_dict(job_report)
    for container in (report, _as_dict(report.get("report"))):
        full = _as_dict(container.get("full"))
        if full:
            return full
    return {}


def _resolve_level(job: OutputAnalyzerJob, observable_type: str, observable_report: object) -> str:
    """Resolve a successful job's level from its TheHive observable report."""
    analyzer_name = job.get("analyzerName", "")
    taxonomies = _extract_taxonomies(observable_report)

    level = "info"
    if not taxonomies:
        log.debug(
            "Analyzer job %s (%s) has no taxonomies in its observable report (keys: %s); defaulting to info",
            job.get("_id"), analyzer_name, sorted(_as_dict(observable_report).keys()),
        )
    if taxonomies:
        if analyzer_name in _LAST_TAXONOMY_ANALYZERS:
            # these analyzers append the relevant taxonomy last
            level = taxonomies[-1].get("level", "info")
        elif analyzer_name == "SpamhausDBL_1_0":
            # the first taxonomy carries a return code instead of a level
            if taxonomies[0].get("value", "NXDOMAIN") in _SPAMHAUS_MALICIOUS_CODES:
                level = "malicious"
        else:
            level = taxonomies[0].get("level", "info")

    # URLhaus reports a threat only in the full report for URLs and hosts
    if analyzer_name == "URLhaus_2_0":
        full = _extract_full_report(job.get("report"))
        if full.get("query_status") == "ok" and full.get("threat"):
            level = "malicious"

    return analyzer_level_mappings.map_level(analyzer_name, observable_type, level)


def _mark_iocs(records: list[_JobRecord], alogger: AnalysisLogger) -> tuple[set[str], set[str]]:
    """Mark observables with a malicious report as IoC.

    Returns:
        The sets of malicious and suspicious observable ids.
    """
    malicious_ids = {record.observable.observable_id for record in records if record.level == "malicious"}
    suspicious_ids = {record.observable.observable_id for record in records if record.level == "suspicious"}

    if malicious_ids:
        try:
            thehive.bulk_update_observables(sorted(malicious_ids), ioc=True)
            alogger.info(f"Marked {len(malicious_ids)} observable(s) as IoC")
        except (TheHiveApiError, ValueError) as exc:
            alogger.warning(f"Could not mark the malicious observable(s) as IoC: {exc}")
    return malicious_ids, suspicious_ids


def _summarize(records: list[_JobRecord], alogger: AnalysisLogger) -> list[str]:
    """Build the short, readable analyzer summary and add it to the analysis log."""
    reports = [record for record in records if record.status == "Success"]
    failed = [record for record in records if record.status in ("Failure", "failed_to_start", "timed_out")]

    lines = [f"Analyzer reports: {len(reports)} collected, {len(failed)} failed"]
    for level, label in (("malicious", "Malicious"), ("suspicious", "Suspicious")):
        lines.extend(
            f"{label}: {record.analyzer_name} on {record.observable.data_type} {record.observable.name}"
            for record in reports if record.level == level
        )
    reasons = {"Failure": "job failed", "failed_to_start": "could not be started", "timed_out": "timed out"}
    lines.extend(
        f"Failed: {record.analyzer_name} on {record.observable.data_type} {record.observable.name} ({reasons[record.status]})"
        for record in failed
    )
    for line in lines:
        alogger.info(line)
    return lines


def run_analyzers(built: BuiltCase, alogger: AnalysisLogger) -> AnalysisOutcome:
    """Run all applicable analyzers on the case and compute the final verdict.

    Raises:
        AnalysisError: If the case observables cannot be listed.
    """
    case_id = built.case["_id"]
    analysis_task_id = built.task_ids.get(ANALYSIS_TASK)
    _update_task_status(analysis_task_id, "InProgress", alogger)
    try:
        thehive.update_case(case_id, status="InProgress")
    except (TheHiveApiError, ValueError) as exc:
        alogger.warning(f"Could not set the case status to InProgress: {exc}")

    try:
        infos = [_observable_info(observable) for observable in thehive.find_all_observables(case_id)]
    except TheHiveApiError as exc:
        raise AnalysisError("Could not list the case observables") from exc

    catalog = _analyzer_catalog({info.data_type for info in infos}, alogger)
    records = _plan_jobs(infos, catalog, alogger)
    if not records:
        alogger.warning("No applicable analyzers found; the verdict is based on no reports")

    _start_jobs(records, alogger)
    _poll_jobs(records, alogger)

    malicious_ids, suspicious_ids = _mark_iocs(records, alogger)
    if malicious_ids:
        verdict = VERDICT_MALICIOUS
    elif suspicious_ids:
        verdict = VERDICT_SUSPICIOUS
    else:
        verdict = VERDICT_SAFE

    summary_lines = _summarize(records, alogger)
    _update_task_status(analysis_task_id, "Completed", alogger)
    return AnalysisOutcome(verdict=verdict, summary_lines=summary_lines)


def _update_task_status(task_id: Optional[str], status: str, alogger: AnalysisLogger) -> None:
    if task_id is None:
        return
    try:
        thehive.update_task(task_id, status=status)
    except (TheHiveApiError, ValueError) as exc:
        alogger.warning(f"Could not set the analysis task to {status}: {exc}")
