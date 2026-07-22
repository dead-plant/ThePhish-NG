"""
Utility module for extracting observables from an EML file.
"""
import email
import email.header
import email.message
import hashlib
import logging
import urllib.parse
from typing import Final

import ioc_finder

log = logging.getLogger(__name__)

# Observable types returned by extract_observables. Every key is always present in the result and matches the corresponding TheHive dataType.
OBSERVABLE_TYPES: Final = (
    'mail',
    'mail-subject',
    'ip',
    'domain',
    'url',
    'hash',
    'registry',
    'user-agent',
    'autonomous-system',
    'filename',
)

# Header fields to consider when searching for observables in the email header.
HEADER_FIELDS: Final = (
    'To',
    'From',
    'Sender',
    'Cc',
    'Delivered-To',
    'Return-Path',
    'Reply-To',
    'Bounces-to',
    'Received',
    'X-Received',
    'X-OriginatorOrg',
    'X-Sender-IP',
    'X-Originating-IP',
    'X-SenderIP',
    'X-Originating-Email',
)

# Mimetypes of the body parts to search for observables.
_TEXT_MIMETYPES: Final = ('text/plain', 'text/html')


def _parse_eml(eml: bytes | str | email.message.Message) -> email.message.Message:
    """Validate the passed eml and parse it into a Message if it is not one already.

    Args:
        eml: The email as raw bytes, as a string, or as an already parsed
            email.message.Message object.

    Returns:
        The parsed email.message.Message.

    Raises:
        ValueError: If the passed eml is None, empty or of an unsupported type.
    """
    if isinstance(eml, email.message.Message):
        return eml
    if isinstance(eml, bytes):
        if not eml.strip():
            raise ValueError("Eml cannot be empty.")
        return email.message_from_bytes(eml)
    if isinstance(eml, str):
        if not eml.strip():
            raise ValueError("Eml cannot be empty.")
        return email.message_from_string(eml)
    raise ValueError("Eml must be bytes, str or an email.message.Message.")


def _decode_header_value(value: str) -> str:
    """Decode a MIME encoded-word header value (RFC 2047) to a plain string.

    The value might be split in two or more differently encoded parts,
    which are decoded separately and joined.

    Args:
        value: The raw header value.

    Returns:
        The decoded header value. Parts with an unknown or invalid charset
        are decoded with replacement characters instead of raising.
    """
    decoded_parts = []
    for data, charset in email.header.decode_header(value):
        if isinstance(data, str):
            decoded_parts.append(data)
        elif charset and charset != 'unknown-8bit':
            try:
                decoded_parts.append(data.decode(charset))
            except (LookupError, UnicodeDecodeError):
                decoded_parts.append(data.decode(errors='replace'))
        else:
            decoded_parts.append(data.decode(errors='replace'))
    return ''.join(decoded_parts)


def _search_text(buffer: str) -> dict[str, list[str]]:
    """Search a text buffer for observables using ioc_finder.

    Args:
        buffer: The text to search.

    Returns:
        A dict mapping the observable types 'mail', 'ip', 'domain', 'url',
        'hash', 'registry', 'user-agent' and 'autonomous-system' to the list
        of values found in the buffer.
    """
    found = {
        'mail': ioc_finder.parse_email_addresses(buffer),
        'ip': ioc_finder.parse_ipv4_addresses(buffer) + ioc_finder.parse_ipv6_addresses(buffer),
        'domain': ioc_finder.parse_domain_names(buffer),
        # Option to parse URLs without a scheme (e.g. without https://)
        'url': ioc_finder.parse_urls(buffer, parse_urls_without_scheme=False),
        # All hash types accepted by the TheHive 'hash' dataType
        # (ssdeep is left out on purpose: its pattern matches random base64 fragments,
        # which are very common in HTML emails, and produces too many false positives)
        'hash': (
            ioc_finder.parse_md5s(buffer)
            + ioc_finder.parse_sha1s(buffer)
            + ioc_finder.parse_sha256s(buffer)
            + ioc_finder.parse_sha512s(buffer)
        ),
        'registry': ioc_finder.parse_registry_key_paths(buffer),
        'user-agent': ioc_finder.parse_user_agents(buffer),
        'autonomous-system': ioc_finder.parse_asns(buffer),
    }
    log.debug(
        "Searched buffer of %d chars: %s",
        len(buffer), {obs_type: len(values) for obs_type, values in found.items()},
    )
    return found


def extract_observables(eml: bytes | str | email.message.Message) -> dict[str, list[str]]:
    """Extract all observables from an EML file.

    Searches the relevant header fields and the text/plain and text/html body
    parts for mail, ip, domain, url, hash, registry, user-agent and
    autonomous-system observables, extracts the subject and collects the
    filename and SHA-256 hash of every attachment. Values are deduplicated
    per type while preserving the order in which they were found.

    Args:
        eml: The email as raw bytes, as a string, or as an already parsed
            email.message.Message object.

    Returns:
        A dict with a list of found values for every type in OBSERVABLE_TYPES,
        e.g. {'mail': [...], 'mail-subject': [...], 'ip': [...], ...}.
        Types without findings map to an empty list.

    Raises:
        ValueError: If the passed eml is None, empty or of an unsupported type.
    """
    msg = _parse_eml(eml)

    observables: dict[str, list[str]] = {obs_type: [] for obs_type in OBSERVABLE_TYPES}

    # Obtain the subject of the email
    if msg['Subject'] is not None:
        subject = _decode_header_value(msg['Subject'])
        if subject.strip():
            observables['mail-subject'].append(subject)
            log.debug("Found subject %r", subject)

    # Search the observables in the values of all the selected header fields
    # Iterating over items() also covers fields that appear more than once (e.g. Received:)
    for field, value in msg.items():
        if field in HEADER_FIELDS:
            log.debug("Searching header field %r for observables", field)
            for obs_type, values in _search_text(_decode_header_value(str(value))).items():
                observables[obs_type].extend(values)

    # Walk the multipart structure of the email
    for part in msg.walk():
        mimetype = part.get_content_type()

        # Extract attachments (filename and hash only, the file content itself is not an observable value)
        if part.get_content_disposition() == 'attachment':
            filename = part.get_filename()
            payload = part.get_payload(decode=True)
            if filename and payload is not None:
                observables['filename'].append(filename)
                sha256 = hashlib.sha256(payload).hexdigest()
                observables['hash'].append(sha256)
                log.debug("Found attachment %r with sha256 %s", filename, sha256)

        # Extract the observables from the body (from both text/plain and text/html parts)
        elif mimetype in _TEXT_MIMETYPES:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            try:
                body = payload.decode()
            except UnicodeDecodeError:
                body = payload.decode('ISO-8859-1')
            if mimetype == 'text/html':
                # Handle URL encoding
                body = urllib.parse.unquote(body.replace("&amp;", "&"))
            log.debug("Searching %s body part for observables", mimetype)
            for obs_type, values in _search_text(body).items():
                observables[obs_type].extend(values)

    # Workaround to prevent HTML tags to appear inside the URLs (splits on < or >)
    observables['url'] = [url.replace(">", "<").split("<")[0] for url in observables['url']]

    # Deduplicate every list while preserving the order in which the values were found
    for obs_type in observables:
        observables[obs_type] = list(dict.fromkeys(observables[obs_type]))

    log.debug(
        "Extracted observables: %s",
        {obs_type: len(values) for obs_type, values in observables.items()},
    )
    return observables


def extract_attachments(eml: bytes | str | email.message.Message) -> list[tuple[str, bytes]]:
    """Extract the attachments of an EML file with their content.

    Companion to extract_observables for creating 'file' observables, which
    need the actual file content instead of a string value.

    Args:
        eml: The email as raw bytes, as a string, or as an already parsed
            email.message.Message object.

    Returns:
        A list of (filename, content) tuples, one per attachment, in the
        order in which the attachments appear in the email.

    Raises:
        ValueError: If the passed eml is None, empty or of an unsupported type.
    """
    msg = _parse_eml(eml)

    attachments = []
    for part in msg.walk():
        if part.get_content_disposition() == 'attachment':
            filename = part.get_filename()
            payload = part.get_payload(decode=True)
            if filename and payload is not None:
                attachments.append((filename, payload))
                log.debug("Extracted attachment %r (%d bytes)", filename, len(payload))

    log.debug("Extracted %d attachment(s)", len(attachments))
    return attachments
