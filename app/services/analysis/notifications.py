"""Sending notification and result emails to the reporter via mail responders.

Prefers the custom PhishMailer responder (which supports a custom subject)
and falls back to the standard Mailer responder. Notification failures are
recorded as warnings and never abort an otherwise successful analysis.
"""

import logging
import re
import time
from typing import Final, Optional

import ioc_fanger
from email_validator import EmailNotValidError, validate_email
from thehive4py.types.cortex import OutputResponder

from app import config
from app.repositories import thehive
from app.repositories.thehive import TheHiveApiError
from app.services.analysis.analyzers import AnalysisOutcome
from app.services.analysis.case_builder import CASE_TITLE_PREFIX, NOTIFICATION_TASK, RESULT_TASK, BuiltCase
from app.services.analysis.events import EventSink

log = logging.getLogger(__name__)

# Template of the optional link included in analysis emails.
ANALYSIS_LINK_LABEL: Final = "View the analysis in ThePhish-NG:"
ANALYSIS_LINK_TEMPLATE: Final = "{base_url}/analysis/{analysis_id}"

_PHISHMAILER_PREFIX: Final = "PhishMailer"
_MAILER_PREFIX: Final = "Mailer"

RESPONDER_POLL_INTERVAL: Final[float] = 2.0  # seconds between responder status polls
RESPONDER_TIMEOUT: Final[float] = 180.0  # seconds before a responder run is given up
POLL_MAX_ERRORS = 3 # max errors before the job is canceled

_TERMINAL_ACTION_STATUSES: Final = ("Success", "Failure")

_MAX_SUBJECT_LENGTH: Final = 120  # PhishMailer rejects longer subjects


def _notification_settings() -> dict:
    return config.get_app_config()["notifications"]


def _select_recipient(submitter: str) -> str:
    override = _notification_settings()["recipient_override"].strip()
    return override or submitter


def _analysis_link_lines(analysis_id: str) -> list[str]:
    if not _notification_settings()["include_analysis_link"]:
        return []
    return [
        "",
        ANALYSIS_LINK_LABEL,
        ANALYSIS_LINK_TEMPLATE.format(
            base_url=config.get_app_config()["webapp"]["base_url"],
            analysis_id=analysis_id,
        ),
    ]


def _validate_recipient(address: str) -> Optional[str]:
    """Return the normalized recipient address, or None if it is invalid."""
    if not isinstance(address, str):
        return None
    try:
        return validate_email(address.strip(), check_deliverability=False).normalized
    except EmailNotValidError:
        return None


def _sanitize_subject(subject: str) -> str:
    """Make a subject safe for a quoted PhishMailer directive field.

    Defanged as well, so a URL in the analyzed email's subject never becomes
    clickable in the notification.
    """
    subject = ioc_fanger.defang(subject)
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
    api_errors = 0
    while time.monotonic() < deadline and api_errors < POLL_MAX_ERRORS:
        time.sleep(RESPONDER_POLL_INTERVAL)
        try:
            action = thehive.get_responder_action("Task", task_id)
        except TheHiveApiError as exc:
            log.debug("Polling responder action on task %s failed (%s)", task_id, exc)
            api_errors += 1
            continue
        # reset api errors after successful poll
        api_errors = 0
        if action.get("status") in _TERMINAL_ACTION_STATUSES:
            return action["status"] == "Success"
    return False


def _format_log_lines(entries: list[dict]) -> list[str]:
    return [f"[{entry.get('timestamp', '')}] {entry.get('level', ''):<7} {entry.get('message', '')}" for entry in entries]


class Notifier:
    """Stage that sends the reporter emails of one analysis."""

    def __init__(self, events: EventSink) -> None:
        self._events = events

    def send_analysis_started(self, built: BuiltCase, recipient: str, analysis_id: str) -> None:
        """Notify the reporter that the analysis of their email has started."""
        settings = _notification_settings()
        title = built.case["title"].removeprefix(CASE_TITLE_PREFIX)
        body_lines = [
            ioc_fanger.defang(f"Thanks for the submission. Your e-mail with subject [{title}] is being analyzed."),
            *_analysis_link_lines(analysis_id),
        ]
        self._send_task_mail(
            task_id=built.task_ids.get(NOTIFICATION_TASK),
            recipient=recipient,
            subject=f"ThePhish: your reported email [{title}] is being analyzed",
            body="\n".join(body_lines),
            mail_label="notification email",
            send_enabled=settings["send_start"],
        )

    def send_analysis_result(self, built: BuiltCase, recipient: str, analysis_id: str, outcome: AnalysisOutcome, transcript: list[dict]) -> None:
        """Prepare the configurable final result notification and optionally deliver it.

        The transcript is the snapshot of the analysis log entries recorded so
        far (already defanged by the sink), so an included log stays complete
        even if individual Redis log writes failed. Verdict, summary, log, and
        analysis-link content follow notification settings; all content derived
        from the analyzed email is defanged, while the optional analysis link
        is the only clickable URL in the notification.
        """
        settings = _notification_settings()
        include_verdict = settings["include_verdict"]
        title = built.case["title"].removeprefix(CASE_TITLE_PREFIX)

        if include_verdict:
            subject = f"ThePhish verdict: {outcome.verdict} [{title}]"
            body_lines = [
                ioc_fanger.defang(
                    f"Thanks for your submission. The e-mail with subject [{title}] "
                    f"has been classified as {outcome.verdict}."
                ),
                *_analysis_link_lines(analysis_id),
                "",
                f"Final verdict: {outcome.verdict}",
                "",
                "--- Analyzer summary ---",
                *(ioc_fanger.defang(line) for line in outcome.summary_lines),
            ]
            if settings["include_log"]:
                body_lines.extend([
                    "",
                    "--- Analysis log ---",
                    *_format_log_lines(transcript),
                ])
        else:
            subject = f"ThePhish: analysis complete [{title}]"
            body_lines = [
                ioc_fanger.defang(
                    f"Thanks for your submission. The analysis of the e-mail with subject "
                    f"[{title}] is complete. Please review the TheHive case or contact "
                    "your administrator for the result."
                ),
                *_analysis_link_lines(analysis_id),
            ]

        send_enabled = settings[f"send_result_{outcome.verdict.lower()}"]
        self._send_task_mail(
            task_id=built.task_ids.get(RESULT_TASK),
            recipient=recipient,
            subject=subject,
            body="\n".join(body_lines),
            mail_label="result email",
            send_enabled=send_enabled,
        )

    def _send_task_mail(self,
        task_id: Optional[str],
        recipient: str,
        subject: str,
        body: str,
        mail_label: str,
        send_enabled: bool,
    ) -> None:
        """Write a responder-formatted task description and optionally send it, best-effort."""
        if task_id is None:
            self._events.warning(f"Could not send the {mail_label}: the case task is missing")
            return
        validated_recipient = _validate_recipient(_select_recipient(recipient))
        if validated_recipient is None:
            self._events.warning(f"Could not send the {mail_label}: the recipient address is not a safe email address")
            return

        try:
            responder = _select_mail_responder(task_id)
            if responder is None:
                self._events.warning(f"Could not send the {mail_label}: no mail responder is enabled")
                return

            description = _build_description(responder["name"], validated_recipient, _sanitize_subject(subject), body)
            if not send_enabled:
                thehive.update_task(task_id, description=description)
                return
            thehive.update_task(task_id, description=description, status="InProgress")
            thehive.create_responder_action(responder_id=responder["id"], object_type="case_task", object_id=task_id)
            if _wait_for_responder(task_id):
                self._events.info(f"Sent the {mail_label} via {responder['name']}")
            else:
                self._events.warning(f"The {mail_label} could not be delivered by {responder['name']}")
            thehive.update_task(task_id, status="Completed")
        except (TheHiveApiError, ValueError) as exc:
            self._events.warning(f"Could not send the {mail_label}: {exc}")
