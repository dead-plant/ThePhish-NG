"""Listing and retrieval of analyzable emails.

An "analyzable" email is an unread email in the configured mailbox that carries
a forwarded suspicious email as an EML attachment. The Parent email is required to have a sender, subject and date.
"""

import email
import email.header
import email.message
import email.utils
import logging
from dataclasses import dataclass
from typing import Optional

import bs4
# different imports on windows/linux (python-magic-bin / python-magic)
try:
    import magic.magic as magic
except ImportError:
    import magic

from app import config
from app.repositories import imap_pool

log = logging.getLogger(__name__)

# MIME types under which mail clients deliver a forwarded email attachment.
_EML_MIME_TYPES = ("message/rfc822", "application/octet-stream")


@dataclass(frozen=True)
class AnalyzableEmail:
    uid: int
    sender: str
    subject: str
    date: str
    body: str
    attached_subject: str


class InvalidEmailError(Exception):
    """The email doesn't contain all needed information or is misformed."""


class EmailNotFoundError(Exception):
    """No unread email with the given UID exists."""


def _decode_header(raw: Optional[str]) -> str:
    """Decode a possibly RFC 2047-encoded header into a plain string.

    Returns '' for missing headers. Never raises on malformed input: unknown
    or broken charsets fall back to a lossy utf-8 decode.
    """
    if raw is None:
        return ""
    parts = []
    for value, charset in email.header.decode_header(raw):
        if isinstance(value, str):
            parts.append(value)
            continue
        if charset and charset.lower() != "unknown-8bit":
            try:
                parts.append(value.decode(charset, errors="replace"))
                continue
            except LookupError:
                pass  # bogus charset name, fall through
        parts.append(value.decode("utf-8", errors="replace"))
    return "".join(parts).strip()


def _decode_text_payload(part: email.message.Message) -> str:
    """Decode the payload of a text/* part, tolerating charset lies."""
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _extract_eml_attachment(msg: email.message.Message) -> Optional[email.message.Message]:
    """Return the attached EML as a Message, or None if absent/malformed.

    Handles both message/rfc822 parts and application/octet-stream parts that
    actually contain an email (verified with libmagic).
    """
    for part in msg.walk():
        mimetype = part.get_content_type()
        if mimetype not in _EML_MIME_TYPES:
            continue

        if mimetype == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list) and payload and isinstance(payload[0], email.message.Message):
                return payload[0]
            raw = part.get_payload(decode=True)
            if raw:
                try:
                    return email.message_from_bytes(raw)
                except Exception:
                    log.debug("Failed to parse message/rfc822 payload", exc_info=True)
            return None

        # application/octet-stream
        raw = part.get_payload(decode=True)
        if not raw:
            continue
        if magic.from_buffer(raw, mime=True) not in ("text/plain", "message/rfc822"):
            continue
        try:
            return email.message_from_bytes(raw)
        except Exception:
            log.debug("Failed to parse octet-stream payload as email", exc_info=True)
            return None

    return None


def _extract_body(msg: email.message.Message) -> str:
    """Extract a plain-text body from the parent email.

    Prefers a text/plain part; falls back to stripping tags from the first
    text/html part. Stops at the message/rfc822 part, because anything after
    it belongs to the attached email, not the parent. Returns '' if no body
    is found (a missing body does not make the email invalid).
    """
    html_fallback = None
    for part in msg.walk():
        mimetype = part.get_content_type()
        if mimetype == "message/rfc822":
            break
        if mimetype == "text/plain":
            text = _decode_text_payload(part)
            if text:
                return text
        elif mimetype == "text/html" and html_fallback is None:
            html_fallback = _decode_text_payload(part)

    if html_fallback:
        # get_text() is safe on arbitrary/malicious markup, unlike navigating
        # a fixed tag path which raises on any unexpected structure.
        soup = bs4.BeautifulSoup(html_fallback, "html.parser")
        return soup.get_text(separator="\n", strip=True)
    return ""


def _parse_and_validate(uid: int, raw_message: bytes) -> tuple[AnalyzableEmail, email.message.Message]:
    """Parse a raw RFC822 message and validate it as analyzable.

    Returns the listing dataclass together with the attached EML Message.
    Raises InvalidEmailError if required headers are missing or the
    EML attachment is missing/malformed.
    """
    try:
        msg = email.message_from_bytes(raw_message)
    except Exception as exc:
        raise InvalidEmailError("Unparsable RFC822 message") from exc

    sender = _decode_header(msg["From"])
    subject = _decode_header(msg["Subject"])
    date = (msg["Date"] or "").strip()
    if not sender or not subject or not date:
        raise InvalidEmailError("Missing required header(s): " + ", ".join(name for name, value in (("From", sender), ("Subject", subject), ("Date", date)) if not value))

    internal_msg = _extract_eml_attachment(msg)
    if internal_msg is None:
        raise InvalidEmailError("Missing or malformed EML attachment")

    info = AnalyzableEmail(
        uid=uid,
        sender=sender,
        subject=subject,
        date=date,
        body=_extract_body(msg),
        attached_subject=_decode_header(internal_msg["Subject"]),
    )
    return info, internal_msg


def list_analyzable(mark_invalid_seen: bool = True) -> list[AnalyzableEmail]:
    """List all unread emails that are valid for analysis.

    At most 'email_list_amount' valid emails are returned; invalid emails do not count toward that limit (larger than max size, missing headers or missing/malformed EML attachment).
    """
    imap_config = config.get_app_config()["imap"]
    limit = imap_config["email_list_amount"]
    max_message_size = imap_config["max_message_size_mb"] * 1024 * 1024

    with imap_pool.get_pool().connection() as connection:
        message_ids = connection.search(["UNSEEN"])
        log.debug("%d unread message(s) to inspect", len(message_ids))

        # Fetch the sizes up front, so oversized emails are rejected
        sizes = connection.fetch(message_ids, ["RFC822.SIZE"]) if message_ids else {}

        analyzable = []
        invalid_count = 0
        for uid in message_ids:
            if len(analyzable) >= limit:
                break

            try:
                if sizes[uid][b"RFC822.SIZE"] > max_message_size:
                    raise InvalidEmailError(f"Message size {sizes[uid][b'RFC822.SIZE']} exceeds the {max_message_size} byte limit"
                                            )
                data = connection.fetch([uid], ["BODY.PEEK[]"])
                info, _ = _parse_and_validate(uid, data[uid][b"BODY[]"])
            except InvalidEmailError as exc:
                invalid_count += 1
                log.debug("Email %d is not analyzable: %s", uid, exc)
                if mark_invalid_seen:
                    connection.add_flags([uid], ["\\Seen"])
                continue
            log.debug("Email %d from %s, subject %r is analyzable", uid, info.sender, info.subject)
            analyzable.append(info)

        if invalid_count:
            log.warning("Skipped %d invalid email(s)" + ". Marked invalid emails as seen" if mark_invalid_seen else "", invalid_count)
        log.debug("%d analyzable email(s) found", len(analyzable))
        return analyzable


def fetch_analyzable_eml(mail_uid: int) -> tuple[email.message.Message, str]:
    """Fetch one email by UID and return (attached EML, parent sender address).

    The fetch flags the email as seen.
    Raises EmailNotFoundError if the UID is no longer among the unread emails and InvalidEmailError if it fails validation.
    """
    mail_uid = int(mail_uid)
    max_message_size = config.get_app_config()["imap"]["max_message_size_mb"] * 1024 * 1024

    with imap_pool.get_pool().connection() as connection:
        if mail_uid not in connection.search(["UNSEEN"]):
            raise EmailNotFoundError(f"No unread email with UID {mail_uid}; it may already be analyzed")

        size = connection.fetch([mail_uid], ["RFC822.SIZE"])[mail_uid][b"RFC822.SIZE"]
        if size > max_message_size:
            raise InvalidEmailError(f"Message size {size} exceeds the {max_message_size} byte limit")

        data = connection.fetch([mail_uid], ["RFC822"])
        log.debug("Email %d fetched for analysis", mail_uid)

        info, internal_msg = _parse_and_validate(mail_uid, data[mail_uid][b"RFC822"])

        # Reduce "Name <addr>" to the bare address used to send the verdict.
        _, sender_address = email.utils.parseaddr(info.sender)
        return internal_msg, sender_address or info.sender
