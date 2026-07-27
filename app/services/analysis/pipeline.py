"""Starting analyses and running the high-level analysis workflow.

The Flask request only validates the mail UID, stores the initial state and
queues the Celery task; all long-running work happens in the task.
"""

import logging
import uuid

from celery import shared_task

from app.repositories import imap_pool, mailbox
from app.services.analysis import analyzers, case_builder, notifications, tracking
from app.services.analysis.errors import AnalysisError, AnalysisQueueError, AnalysisStorageError, InvalidMailUidError
from app.services.analysis.tracking import AnalysisLogger

log = logging.getLogger(__name__)


def _validate_mail_uid(mail_uid: object) -> int:
    """Return the mail UID as a positive int, accepting numeric strings.

    Raises:
        InvalidMailUidError: If the value is not a positive integer.
    """
    if isinstance(mail_uid, int) and not isinstance(mail_uid, bool):
        uid = mail_uid
    elif isinstance(mail_uid, str) and mail_uid.strip().isdigit():
        uid = int(mail_uid.strip())
    else:
        raise InvalidMailUidError("mail_uid must be a positive integer")
    if uid <= 0:
        raise InvalidMailUidError("mail_uid must be a positive integer")
    return uid


def start_analysis(mail_uid: object) -> dict:
    """Validate the mail UID, store the initial state and queue the analysis.

    Returns:
        The initial analysis state including the new analysis_id.

    Raises:
        InvalidMailUidError: If the mail UID is not a positive integer.
        AnalysisStorageError: If the initial state cannot be stored in Redis.
        AnalysisQueueError: If the Celery task cannot be queued.
    """
    uid = _validate_mail_uid(mail_uid)
    analysis_id = uuid.uuid4().hex
    state = tracking.create_analysis(analysis_id, uid)

    try:
        run_analysis.delay(analysis_id, uid)
    except Exception as exc:  # broker outages surface as varied kombu/redis errors, so the queue boundary is deliberately broad
        log.error("Could not queue analysis %s", analysis_id, exc_info=exc)
        tracking.mark_failed(analysis_id, "The analysis task could not be queued")
        raise AnalysisQueueError("The analysis backend is unavailable") from exc

    log.info("Queued analysis %s for mail UID %d", analysis_id, uid)
    return state


@shared_task(name="app.services.analysis.run_analysis")
def run_analysis(analysis_id: str, mail_uid: int) -> None:
    _execute_analysis(analysis_id, mail_uid)


def _execute_analysis(analysis_id: str, mail_uid: int) -> None:
    """Run one analysis inside the Celery task and record its outcome.

    Never raises: fatal errors mark the analysis as failed with a useful
    error message and the finish timestamp.
    """
    alogger = AnalysisLogger(analysis_id)
    try:
        tracking.set_state_fields(analysis_id, status=tracking.STATUS_RUNNING, started_at=tracking.utc_now_iso())
    except AnalysisStorageError as exc:
        log.error("Could not mark analysis %s as running; aborting", analysis_id, exc_info=exc)
        tracking.mark_failed(analysis_id, "The analysis state storage is unavailable")
        return
    alogger.info(f"Analysis started for email UID {mail_uid}")

    try:
        verdict = _run_workflow(analysis_id, mail_uid, alogger)
    except AnalysisError as exc:
        log.error("Analysis %s failed", analysis_id, exc_info=exc)
        alogger.error(f"Analysis failed: {exc}")
        tracking.mark_failed(analysis_id, str(exc))
        return
    except Exception as exc:  # Celery task boundary: any unexpected error must be recorded
        log.exception("Unexpected error aborted analysis %s", analysis_id)
        alogger.error("An unexpected internal error aborted the analysis")
        tracking.mark_failed(analysis_id, f"Unexpected internal error ({type(exc).__name__})")
        return

    try:
        tracking.set_state_fields(analysis_id, status=tracking.STATUS_FINISHED, verdict=verdict, finished_at=tracking.utc_now_iso())
    except AnalysisStorageError as exc:
        log.error("Could not mark analysis %s as finished", analysis_id, exc_info=exc)
    log.info("Analysis %s finished with verdict %s", analysis_id, verdict)


def _run_workflow(analysis_id: str, mail_uid: int, alogger: AnalysisLogger) -> str:
    """Coordinate the analysis stages and return the final verdict.

    Composition root of one analysis execution: the per-analysis event sink
    is injected once into each stage here.

    Raises:
        AnalysisError: If a fatal stage (fetching the email, creating the
            case, running the analyzers) fails.
    """
    try:
        internal_msg, reporter_address = mailbox.fetch_analyzable_eml(mail_uid)
    except (mailbox.EmailNotFoundError, mailbox.InvalidEmailError) as exc:
        raise AnalysisError(f"Could not fetch the email with UID {mail_uid}: {exc}") from exc
    except (imap_pool.IMAPConnectionError, imap_pool.PoolTimeoutError, imap_pool.PoolClosedError) as exc:
        raise AnalysisError("Could not fetch the email: the IMAP mailbox is unavailable") from exc
    alogger.info(f"Fetched the email with UID {mail_uid} (flagged as read)")

    builder = case_builder.CaseBuilder(alogger)
    runner = analyzers.AnalyzerRunner(alogger)
    notifier = notifications.Notifier(alogger)

    built = builder.build_case(internal_msg)
    tracking.set_state_fields(analysis_id, case_id=built.case["_id"], case_number=str(built.case["number"]))

    notifier.send_analysis_started(built, reporter_address)

    outcome = runner.run(built)
    alogger.info(f"The email has been classified as {outcome.verdict}")

    builder.finalize_case(built, outcome.verdict)
    notifier.send_analysis_result(built, reporter_address, analysis_id, outcome, alogger.snapshot())
    return outcome.verdict
