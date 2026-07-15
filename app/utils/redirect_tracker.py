"""
Utility module for tracking http redirects and returning the target url.
"""
import logging
from typing import Final

log = logging.getLogger(__name__)

MAX_DEPTH: Final[int] = 15

class RedirectTrackerError(Exception):
    """Raised when tracking an url destination fails."""


class InvalidUrlError(RedirectTrackerError):
    """Raised when an invalid url is passed."""


class MaxRedirectDepthError(RedirectTrackerError):
    """Raised when tracking a url takes more redirects than the max depth."""
    def __init__(self, last_url: str, trace: list[str]) -> None:
        self.last_url = last_url
        self.trace = trace
        super().__init__(f"Reached max depth of {MAX_DEPTH} without finding the target url.")

class LoopingRedirectError(RedirectTrackerError):
    """Raised when tracking a url returns to a url previously visited."""
    def __init__(self, last_url: str, trace: list[str]) -> None:
        self.last_url = last_url
        self.trace = trace
        super().__init__("Found looping redirect.")


def get_trace(url: str) -> list[str] | None:
    """Get the full redirect trace from the passed URL, including the final destination.
        Args:
            url: The URL to get the trace of.

        Returns:
            The full redirect trace from the passed URL.

        Raises:
            ValueError: If the passed URL is None or an empty string.
            RedirectTrackerError: If tracking the redirects fails.
            InvalidUrlError: If the passed URL is invalid.
            MaxRedirectDepthError: If finding the destination of the passed URL takes more redirects than the max depth.
            LoopingRedirectError: If a redirect loop is encountered while finding the destination.
    """
    ...


def get_destination(url: str) -> str | None:
    """Get the final destination of a URL. Return None if the passed URL does not redirect.
        Args:
            url: The URL to get the destination of.

        Returns:
            The final destination of the URL, or None.

        Raises:
            ValueError: If the passed URL is None or an empty string.
            RedirectTrackerError: If tracking the redirects fails.
            InvalidUrlError: If the passed URL is invalid.
            MaxRedirectDepthError: If finding the destination of the passed URL takes more redirects than the max depth.
            LoopingRedirectError: If a redirect loop is encountered while finding the destination.
    """
    trace = get_trace(url)
    if trace:
        return trace[-1]
    else:
        return None
