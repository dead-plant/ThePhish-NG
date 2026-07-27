"""Building the TheHive case for an analysis.

Extracts and filters the observables of the reported email, expands URLs
(Outlook SafeLinks, HTTP redirects), creates the case from the ThePhish
template and adds the observables, the attachments and the original EML.
"""

import email.message
import email.utils
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Final, Optional

import emoji
from thehive4py.types.case import OutputCase
# different imports on windows/linux (python-magic-bin / python-magic)
try:
    import magic.magic as magic
except ImportError:
    import magic

from app import config
from app.repositories import thehive
from app.repositories.thehive import TheHiveApiError
from app.services.analysis.errors import AnalysisError
from app.services.analysis.events import EventSink
from app.utils import observable_extractor, redirect_tracker, safelink_decoder, whitelist
from app.utils.redirect_tracker import RedirectTrackerError
from app.utils.safelink_decoder import SafeLinkDecodingError

log = logging.getLogger(__name__)

# Case template used for every ThePhish case.
CASE_TEMPLATE_NAME: Final = "ThePhish"
CASE_TITLE_PREFIX: Final = "[ThePhish] "
NOTIFICATION_TASK: Final = "ThePhish notification"
ANALYSIS_TASK: Final = "ThePhish analysis"
RESULT_TASK: Final = "ThePhish result"
TASK_TITLES: Final = (NOTIFICATION_TASK, ANALYSIS_TASK, RESULT_TASK)

# Tags that mark special observables for the analyzer stage.
SENDER_DOMAIN_TAG: Final = "email_sender_domain"
EML_SAMPLE_TAG: Final = "email_sample"

# Observable types with whitelist support (matching whitelist.is_whitelisted).
_WHITELISTED_TYPES: Final = frozenset({"mail", "ip", "domain", "url", "hash", "filename"})


@dataclass(frozen=True)
class BuiltCase:
    """The created case together with its task ids, keyed by task title."""
    case: OutputCase
    task_ids: dict[str, str]


def sender_domain(internal_msg: email.message.Message) -> Optional[str]:
    """Return the domain of the attached email's From address, or None.

    This is the only domain the SPF/DMARC analyzer may run against, so it is
    derived from the sender address itself instead of the extracted domains.
    """
    _, address = email.utils.parseaddr(str(internal_msg.get("From", "")))
    if "@" not in address:
        return None
    domain = address.rpartition("@")[2].strip().strip(".").lower()
    return domain or None


def _write_temp_file(directory: str, filename: str, content: bytes) -> str:
    """Write an attachment into the temp directory under a safe, unique name."""
    safe_name = os.path.basename(filename.replace("\\", "/")).strip() or "attachment"
    safe_name = re.sub(r"[\x00-\x1f]", "", safe_name)
    path = os.path.join(directory, safe_name)
    base, ext = os.path.splitext(safe_name)
    counter = 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{base}_{counter}{ext}")
        counter += 1
    with open(path, "wb") as file:
        file.write(content)
    return path


class CaseBuilder:
    """Stage that owns the TheHive case lifecycle of one analysis."""

    def __init__(self, events: EventSink) -> None:
        self._events = events

    def build_case(self, internal_msg: email.message.Message) -> BuiltCase:
        """Create the TheHive case for the reported email and populate it.

        A failure to add a single observable or attachment is logged as a
        warning; a failure to create the case itself is fatal.

        Raises:
            AnalysisError: If the case (or its template) cannot be created.
        """
        observables = observable_extractor.extract_observables(internal_msg)
        raw_subject = observables["mail-subject"][0] if observables["mail-subject"] else ""
        subject = re.sub(r"(?:[ \t]*[\r\n]+)+[ \t]*", " ", raw_subject).strip()

        self._events.info(f"Analyzing attached email with subject: {subject!r}")

        try:
            thehive.create_case_template_unless_exists(
                name=CASE_TEMPLATE_NAME,
                title_prefix=CASE_TITLE_PREFIX,
                tasks=[{"title": title} for title in TASK_TITLES],
            )
        except TheHiveApiError as exc:
            raise AnalysisError(f"Could not ensure the {CASE_TEMPLATE_NAME} case template") from exc

        case_config = config.get_app_config()["case"]
        # Emojis are removed to prevent problems when exporting the case to MISP.
        title = str(emoji.replace_emoji(subject)).strip() or "(no subject)"
        try:
            case = thehive.create_case(
                title=title,
                tlp=int(case_config["tlp"]),
                pap=int(case_config["pap"]),
                tags=list(case_config["tags"]),
                description="Case created automatically by ThePhish",
                template=CASE_TEMPLATE_NAME,
            )
        except (TheHiveApiError, ValueError) as exc:
            raise AnalysisError("Could not create the TheHive case") from exc
        case_id = case["_id"]
        self._events.info(f"Created case #{case['number']}")

        # The sender domain is added separately with its marker tag, so the
        # SPF/DMARC analyzer can be restricted to it.
        domain_of_sender = sender_domain(internal_msg)
        if domain_of_sender is None:
            self._events.warning("Could not determine the sender domain; the SPF/DMARC analyzer will not run")
        elif whitelist.is_whitelisted("domain", domain_of_sender):
            self._events.info(f"Skipped whitelisted sender domain: {domain_of_sender}")
            domain_of_sender = None
        else:
            self._add_observables(case_id, "domain", [domain_of_sender], ["email", SENDER_DOMAIN_TAG], "Domain of the sender address of the reported email")

        for obs_type in ("mail", "mail-subject", "ip", "domain", "hash", "registry", "user-agent", "autonomous-system", "filename"):
            values = self._filter_whitelisted(obs_type, observables[obs_type])
            if obs_type == "domain" and domain_of_sender in values:
                values.remove(domain_of_sender)
            self._add_observables(case_id, obs_type, values, ["email"], "Found in the reported email")

        url_groups = self._collect_urls(observables["url"])
        self._add_observables(case_id, "url", url_groups["url"], ["email"], "Found in the reported email")
        self._add_observables(case_id, "url", url_groups["safelink_decoded"], ["email", "safelink_decoded"], "Decoded from an Outlook SafeLink found in the email")
        self._add_observables(case_id, "url", url_groups["redirect_target"], ["email", "redirect_target"], "Found by following HTTP redirects of URLs in the email")

        self._add_attachments(case_id, internal_msg, subject)

        try:
            task_ids = {task["title"]: task["_id"] for task in thehive.find_all_tasks(case_id) if task["title"] in TASK_TITLES}
        except TheHiveApiError as exc:
            self._events.warning(f"Could not list the case tasks: {exc}")
            task_ids = {}

        return BuiltCase(case=case, task_ids=task_ids)

    def finalize_case(self, built: BuiltCase, verdict: str) -> None:
        """Close (and for malicious verdicts export) the case; failures are warnings.

        A suspicious verdict leaves the case open for manual review.
        """
        case_id = built.case["_id"]

        if verdict == "Suspicious":
            self._events.info("The verdict is not final: the case stays open for manual review")
            return

        if verdict == "Malicious":
            try:
                thehive.export_case(case_id, config.get_app_config()["thehive"]["misp_id"])
                self._events.info("Exported the case to MISP")
            except (TheHiveApiError, ValueError) as exc:
                self._events.warning(f"Could not export the case to MISP: {exc}")

        resolution = "TruePositive" if verdict == "Malicious" else "FalsePositive"
        try:
            thehive.close_case(case_id=case_id, status=resolution, summary="Automated analysis by ThePhish", impact_status="NoImpact")
            self._events.info(f"Closed the case as {resolution}")
        except (TheHiveApiError, ValueError) as exc:
            self._events.warning(f"Could not close the case: {exc}")

    def _filter_whitelisted(self, obs_type: str, values: list[str]) -> list[str]:
        """Drop empty, multi-line and whitelisted values from an observable list."""
        kept = []
        for value in values:
            value = value.strip()
            if not value:
                continue
            if obs_type in _WHITELISTED_TYPES and whitelist.is_whitelisted(obs_type, value):
                self._events.info(f"Skipped whitelisted {obs_type}: {value}")
                continue
            kept.append(value)
        return kept

    def _decode_safelinks(self, urls: list[str]) -> list[str]:
        """Decode Outlook SafeLinks among the given URLs and return the targets."""
        decoded = []
        for url in urls:
            try:
                if not safelink_decoder.is_safelink(url):
                    continue
                target = safelink_decoder.decode_safelink(url)
            except (SafeLinkDecodingError, ValueError) as exc:
                self._events.warning(f"Could not decode SafeLink {url}: {exc}")
                continue
            self._events.info(f"Decoded SafeLink {url} to {target}")
            decoded.append(target)
        return decoded

    def _expand_redirects(self, urls: list[str]) -> list[str]:
        """Follow the HTTP redirects of the given URLs and return every hop found."""
        targets = []
        for url in urls:
            try:
                trace = redirect_tracker.get_trace(url) or []
            except (RedirectTrackerError, ValueError) as exc:
                self._events.warning(f"Could not follow redirects of {url}: {exc}")
                continue
            if trace:
                self._events.info(f"URL {url} redirects through: {' -> '.join(trace)}")
                targets.extend(trace)
        return targets

    def _collect_urls(self, extracted_urls: list[str]) -> dict[str, list[str]]:
        """Whitelist-filter and expand the extracted URLs.

        Returns:
            Groups of new, deduplicated URLs: 'url' (extracted), 'safelink_decoded'
            and 'redirect_target'. Expansion failures are logged, never fatal.
        """
        analysis_config = config.get_app_config()["analysis"]

        urls = self._filter_whitelisted("url", extracted_urls)

        decoded = []
        if analysis_config["decode_o365_safelinks"]:
            decoded = self._filter_whitelisted("url", self._decode_safelinks(urls))

        redirect_targets = []
        if analysis_config["follow_url_redirects"]:
            redirect_targets = self._filter_whitelisted("url", self._expand_redirects(urls + decoded))

        # Deduplicate across all groups; the first occurrence wins.
        groups = {"url": urls, "safelink_decoded": decoded, "redirect_target": redirect_targets}
        seen: set[str] = set()
        for name, group in groups.items():
            deduplicated = []
            for url in group:
                if url not in seen:
                    seen.add(url)
                    deduplicated.append(url)
            groups[name] = deduplicated
        return groups

    def _add_observables(self, case_id: str, data_type: str, values: list[str], tags: list[str], message: str) -> None:
        """Add a batch of observables to the case; a failure is logged, not fatal."""
        if not values:
            return
        try:
            thehive.create_observable(case_id=case_id, data_type=data_type, data=values, tags=tags, message=message)
            self._events.info(f"Added {len(values)} {data_type} observable(s): {', '.join(values)}")
        except (TheHiveApiError, ValueError) as exc:
            self._events.warning(f"Could not add {data_type} observable(s) {', '.join(values)}: {exc}")

    def _add_attachments(self, case_id: str, internal_msg: email.message.Message, subject: str) -> None:
        """Add the email attachments and the original EML as file observables."""
        attachments = observable_extractor.extract_attachments(internal_msg)

        with tempfile.TemporaryDirectory(prefix="thephish_") as tmp_dir:
            for filename, content in attachments:
                if whitelist.is_whitelisted("filename", filename):
                    self._events.info(f"Skipped whitelisted attachment: {filename}")
                    continue
                filetype = magic.from_buffer(content, mime=True)
                if whitelist.is_whitelisted("filetype", filetype):
                    self._events.info(f"Skipped attachment {filename} with whitelisted type {filetype}")
                    continue
                try:
                    path = _write_temp_file(tmp_dir, filename, content)
                    thehive.create_file_observable(case_id=case_id, file_path=path, tags=["email", "email_attachment"], message="Found as email attachment")
                    self._events.info(f"Added attachment as file observable: {filename}")
                except (TheHiveApiError, ValueError, OSError) as exc:
                    self._events.warning(f"Could not add attachment {filename}: {exc}")

            # Attach the original email, so analyzers like Yara can scan it.
            try:
                eml_path = _write_temp_file(tmp_dir, f"{subject or 'attached_email'}.eml", internal_msg.as_bytes())
                thehive.create_file_observable(case_id=case_id, file_path=eml_path, tags=["email", EML_SAMPLE_TAG], message="Attached email in EML format")
                self._events.info(f"Added the original email as file observable: {os.path.basename(eml_path)}")
            except (TheHiveApiError, ValueError, OSError) as exc:
                self._events.warning(f"Could not attach the original email: {exc}")
