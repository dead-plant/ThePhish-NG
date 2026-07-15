"""
Utility module for working with and decoding Microsoft Office 365 ATP Safe Links
"""
from typing import Final
import logging
import re
import urllib.parse

log = logging.getLogger(__name__)

SAFE_LINK_DOMAIN_PATTERN: Final = re.compile(r'\.safelinks\.protection\.outlook\.com$', re.IGNORECASE)
SAFE_LINK_URL_PARAM_PATTERN: Final = re.compile(r'[?&]url=([^&]+)', re.IGNORECASE)

class SafeLinkDecodingError(Exception):
    """Raised when decoding a safe link fails."""


class NotASafeLinkError(SafeLinkDecodingError):
    """Raised when decoding a URL that isn't a safe link."""


def is_safelink(url: str) -> bool:
    """
    Checks if the URL is a Safe Link.
    Args:
        url: The URL to check

    Returns:
        True if the URL is a Safe Link, False otherwise

    Raises:
        ValueError: If the passed url is None or empty
    """

    if url is None or not url.strip():
        raise ValueError("Url cannot be Null or empty.")

    host = urllib.parse.urlparse(url).hostname
    if host is None:
        log.debug("URL %r has no hostname and is not a Safelink", host)
        return False

    is_safe_link = bool(SAFE_LINK_DOMAIN_PATTERN.search(host.strip()))
    log.debug("Checked if host %r is a Safelink: %s", host, is_safe_link)
    return is_safe_link


def decode_safelink(safelink: str) -> str:
    """Decodes a Microsoft Office 365 ATP Safe Link and returns the target url.
        Args:
            safelink: Safelink to decode

        Returns:
            The target url

        Raises:
            ValueError: If the passed url is None or empty
            NotASafeLinkError: If the URL is not a Safelink
            SafeLinkDecodingError: If decoding fails
    """
    if not is_safelink(safelink):
        raise NotASafeLinkError("Passed url is not a Safelink")

    log.debug("Decoding Safelink %r", safelink)
    url = safelink.strip()
    depth = 0

    while is_safelink(url):
        if depth >= 5:
            raise SafeLinkDecodingError("Reached max depth of 5 without finding the original url.")
        
        match = SAFE_LINK_URL_PARAM_PATTERN.search(url)
        if match:
            try:
                encoded_url = match.group(1)
                url = urllib.parse.unquote(encoded_url)
            except Exception as exc:
                raise SafeLinkDecodingError("Couldn't decode url parameter.") from exc
        else:
            raise SafeLinkDecodingError("Invalid safelink: Link has no url parameter.")

        depth += 1
        log.debug("Decoded Safelink layer %d to %r", depth, url)

    log.debug("Decoded Safelink %r to %r after %d layer(s)", safelink, url, depth)
    return url
