"""Sending notification and result emails to the reporter via mail responders.

Prefers the custom PhishMailer responder (which supports a custom subject)
and falls back to the standard Mailer responder. Notification failures are
recorded as warnings and never abort an otherwise successful analysis.
"""

import logging
import re
import time
from typing import Final, Optional

from thehive4py.types.cortex import OutputResponder

from app.repositories import thehive
from app.repositories.thehive import TheHiveApiError
from app.services.analysis.analyzers import AnalysisOutcome
from app.services.analysis.case_builder import CASE_TITLE_PREFIX, NOTIFICATION_TASK, RESULT_TASK, BuiltCase
from app.services.analysis.tracking import AnalysisLogger

log = logging.getLogger(__name__)

# Placeholder link included at the top of every result email; the frontend
# route behind it will be implemented with the new frontend.
RESULT_LINK_TEMPLATE: Final = "https://thephish.example.com/analysis/{analysis_id}"

_PHISHMAILER_PREFIX: Final = "PhishMailer"
_MAILER_PREFIX: Final = "Mailer"

RESPONDER_POLL_INTERVAL: Final[float] = 2.0  # seconds between responder status polls
RESPONDER_TIMEOUT: Final[float] = 180.0  # seconds before a responder run is given up

_TERMINAL_ACTION_STATUSES: Final = ("Success", "Failure")

# Conservative recipient pattern: no whitespace, quotes, semicolons or angle
# brackets, so an address can never corrupt a responder directive.
_RECIPIENT_PATTERN: Final = re.compile(r"^[^@\s;\"'<>,]+@[^@\s;\"'<>,]+\.[A-Za-z0-9-]{2,}$")
_MAX_SUBJECT_LENGTH: Final = 120  # PhishMailer rejects longer subjects


def _validate_recipient(address: str) -> Optional[str]:
    """Return the normalized recipient address, or None if it is unsafe."""
    if not isinstance(address, str):
        return None
    address = address.strip()
    if len(address) > 254 or not _RECIPIENT_PATTERN.fullmatch(address):
        return None
    return address


def _sanitize_subject(subject: str) -> str:
    """Make a subject safe for a quoted PhishMailer directive field."""
    subject = re.sub(r"[\x00-\x1f\x7f\"]", " ", subject)
    subject = re.sub(r"\s+", " ", subject).strip()
    if len(subject) > _MAX_SUBJECT_LENGTH:
        subject = subject[: _MAX_SUBJECT_LENGTH - 1].rstrip() + "…"
    return subject


def _select_mail_responder(task_id: str) -> Optional[OutputResponder]:
    """Pick the mail responder for a task: PhishMailer if enabled, else Mailer."""
    responders = thehive.list_responders_for_entity("case_task", task_id)
    for prefix in (_PHISHMAILER_PREFIX, _MAILER_PREFIX):
        for responder in responders:
            if responder.get("name", "").startswith(prefix):
                return responder
    return None


def _build_description(responder_name: str, recipient: str, subject: str, body: str) -> str:
    """Build the task description that instructs the responder to send the email."""
    if responder_name.startswith(_PHISHMAILER_PREFIX):
        return f'#{_PHISHMAILER_PREFIX}; subject: "{subject}"; mailto:{recipient};\n{body}'
    # The standard Mailer responder expects "mailto:<address>" on the first
    # line and uses its own default subject.
    return f"mailto:{recipient}\n{body}"


def _wait_for_responder(task_id: str) -> bool:
    """Poll the responder action on a task until it finishes or times out."""
    deadline = time.monotonic() + RESPONDER_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(RESPONDER_POLL_INTERVAL)
        try:
            action = thehive.get_responder_action("Task", task_id)
        except TheHiveApiError as exc:
            log.debug("Polling responder action on task %s failed (%s)", task_id, exc)
            continue
        if action.get("status") in _TERMINAL_ACTION_STATUSES:
            return action["status"] == "Success"
    return False


def _send_task_mail(task_id: Optional[str], recipient: str, subject: str, body: str, mail_label: str, alogger: AnalysisLogger) -> None:
    """Send an email through the mail responder of a case task, best-effort."""
    if task_id is None:
        alogger.warning(f"Could not send the {mail_label}: the case task is missing")
        return
    validated_recipient = _validate_recipient(recipient)
    if validated_recipient is None:
        alogger.warning(f"Could not send the {mail_label}: the reporter address is not a safe email address")
        return

    try:
        responder = _select_mail_responder(task_id)
        if responder is None:
            alogger.warning(f"Could not send the {mail_label}: no mail responder is enabled")
            return

        description = _build_description(responder["name"], validated_recipient, _sanitize_subject(subject), body)
        thehive.update_task(task_id, description=description, status="InProgress")
        thehive.create_responder_action(responder_id=responder["id"], object_type="case_task", object_id=task_id)
        if _wait_for_responder(task_id):
            alogger.info(f"Sent the {mail_label} via {responder['name']}")
        else:
            alogger.warning(f"The {mail_label} could not be delivered by {responder['name']}")
        thehive.update_task(task_id, status="Completed")
    except (TheHiveApiError, ValueError) as exc:
        alogger.warning(f"Could not send the {mail_label}: {exc}")


def send_analysis_started(built: BuiltCase, recipient: str, alogger: AnalysisLogger) -> None:
    """Notify the reporter that the analysis of their email has started."""
    title = built.case["title"].removeprefix(CASE_TITLE_PREFIX)
    _send_task_mail(
        task_id=built.task_ids.get(NOTIFICATION_TASK),
        recipient=recipient,
        subject=f"ThePhish: your reported email [{title}] is being analyzed",
        body=f"Thanks for the submission. Your e-mail with subject [{title}] is being analyzed.",
        mail_label="notification email",
        alogger=alogger,
    )


def _format_log_lines(entries: list[dict]) -> list[str]:
    return [f"[{entry.get('timestamp', '')}] {entry.get('level', ''):<7} {entry.get('message', '')}" for entry in entries]


def send_analysis_result(built: BuiltCase, recipient: str, analysis_id: str, outcome: AnalysisOutcome, alogger: AnalysisLogger) -> None:
    """Send the final result email with the verdict, summary and complete log.

    The log lines are taken from the logger's in-memory entries, so the email
    stays complete even if individual Redis log writes failed.
    """
    title = built.case["title"].removeprefix(CASE_TITLE_PREFIX)
    body_lines = [
        RESULT_LINK_TEMPLATE.format(analysis_id=analysis_id),
        "",
        f"Final verdict: {outcome.verdict}",
        "",
        f"Thanks for your submission. The e-mail with subject [{title}] has been classified as {outcome.verdict}.",
        "",
        "--- Analyzer summary ---",
        *outcome.summary_lines,
        "",
        "--- Analysis log ---",
        *_format_log_lines(alogger.entries),
    ]
    _send_task_mail(
        task_id=built.task_ids.get(RESULT_TASK),
        recipient=recipient,
        subject=f"ThePhish verdict: {outcome.verdict} [{title}]",
        body="\n".join(body_lines),
        mail_label="result email",
        alogger=alogger,
    )
