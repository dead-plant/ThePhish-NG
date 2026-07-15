"""
Utility module for working with and decoding Microsoft Office 365 ATP Safe Links
"""
from typing import Final
import logging
import re
import urllib.parse

log = logging.getLogger(__name__)

MAX_DEPTH: Final[int] = 5

SAFE_LINK_DOMAIN_PATTERN: Final = re.compile(r'\.safelinks\.protection\.outlook\.com$', re.IGNORECASE)

class SafeLinkDecodingError(Exception):
    """Raised when decoding a safe link fails."""


class NotASafeLinkError(SafeLinkDecodingError):
    """Raised when decoding a URL that isn't a safe link."""


class DecodingMaxDepthError(SafeLinkDecodingError):
    """Raised when a safelink passes the max depth limit."""
    def __init__(self, reached_safelink: str) -> None:
        self.url = reached_safelink
        super().__init__(f"Reached max depth of {MAX_DEPTH} without finding the url.")


class LoopingSafeLinkError(SafeLinkDecodingError):
    """Raised when decoding a safelink returns a previous safelink."""
    def __init__(self, looping_safelink: str) -> None:
        self.url = looping_safelink
        super().__init__("Found looping safelink.")

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
        log.debug("URL %r has no hostname and is not a Safelink", url)
        return False

    is_safe_link = bool(SAFE_LINK_DOMAIN_PATTERN.search(host))
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
            DecodingMaxDepthError: If the safelink passes the max depth limit.
            LoopingSafeLinkError: If decoding a safelink returns a previous safelink.
    """
    if not is_safelink(safelink):
        raise NotASafeLinkError("Passed url is not a Safelink")

    log.debug("Decoding Safelink %r", safelink)
    url = safelink.strip()
    history = [url]
    depth = 0

    while is_safelink(url):
        if depth >= MAX_DEPTH:
            raise DecodingMaxDepthError(url)

        try:
            url_params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("url")
        except Exception as exc:
            raise SafeLinkDecodingError("Couldn't decode the safelink.") from exc

        if not url_params or len(url_params) != 1:
            count = len(url_params) if url_params else 0
            raise SafeLinkDecodingError(f"Expected exactly 1 url parameter, got {count}")
        url = url_params[0]

        if not url.strip():
            raise SafeLinkDecodingError("Got empty url.")

        if url in history:
            raise LoopingSafeLinkError(url)
        else:
            history.append(url)

        depth += 1
        log.debug("Decoded Safelink layer %d to %r", depth, url)

    log.debug("Decoded Safelink %r to %r after %d layer(s)", safelink, url, depth)
    return url
