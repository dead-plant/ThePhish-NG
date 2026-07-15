"""
Utility module for tracking http redirects and returning the target url.
"""
import ipaddress
import logging
import socket
import urllib.parse
from typing import Final

import requests

log = logging.getLogger(__name__)

MAX_DEPTH: Final[int] = 15

REQUEST_TIMEOUT: Final[float] = 10.0

# Only these schemes may ever be requested, both for the passed url and for every redirect target.
_ALLOWED_SCHEMES: Final = ("http", "https")

# Status codes that redirect via a Location header.
_REDIRECT_STATUS_CODES: Final = (301, 302, 303, 307, 308)


class RedirectTrackerError(Exception):
    """Raised when tracking an url destination fails."""


class InvalidUrlError(RedirectTrackerError):
    """Raised when an invalid url is passed."""


class InternalAddressError(RedirectTrackerError):
    """Raised when an url or a redirect target resolves to an internal network address.

    Attributes:
        last_url: The last url tracked, the same url get_destination would have
            returned. None if the trace is empty.
        trace: The redirect trace discovered up to this point. Empty if the
            passed url itself is internal.
        internal_address: The internal address because of which the request was denied.
    """
    def __init__(self, trace: list[str], internal_address: str) -> None:
        self.last_url: str | None = trace[-1] if trace else None
        self.trace = trace
        self.internal_address = internal_address
        super().__init__(f"Url resolves to the internal address {internal_address}.")


class MaxRedirectDepthError(RedirectTrackerError):
    """Raised when tracking a url takes more redirects than the max depth.

    Attributes:
        last_url: The last url tracked, the same url get_destination would have
            returned. None if the trace is empty.
        trace: The redirect trace discovered up to this point, ending with last_url.
    """
    def __init__(self, trace: list[str]) -> None:
        self.last_url: str | None = trace[-1] if trace else None
        self.trace = trace
        super().__init__(f"Reached max depth of {MAX_DEPTH} without finding the target url.")

class LoopingRedirectError(RedirectTrackerError):
    """Raised when tracking a url returns to a url previously visited.

    Attributes:
        last_url: The last url tracked, the same url get_destination would have
            returned. None if the trace is empty.
        trace: The redirect trace discovered up to this point, ending with last_url.
    """
    def __init__(self, trace: list[str]) -> None:
        self.last_url: str | None = trace[-1] if trace else None
        self.trace = trace
        super().__init__("Found looping redirect.")


def _require_public_addresses(url: str, hostname: str, trace: list[str]) -> None:
    """Resolve a hostname and raise if any address it resolves to is internal.

    Every address the hostname resolves to (IPv4 and IPv6) must be public,
    otherwise a crafted url or redirect could be abused to make ThePhish
    request internal services (SSRF).

    Args:
        url: The url the hostname belongs to (used for error reporting).
        hostname: The hostname or ip literal to check.
        trace: The redirect trace discovered so far (used for error reporting).

    Raises:
        RedirectTrackerError: If the hostname cannot be resolved.
        InternalAddressError: If the hostname resolves to an internal address.
    """
    addresses = []
    try:
        # ip literal
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        pass

    if not addresses:
        try:
            addrinfo = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise RedirectTrackerError(f"Could not resolve the hostname of {url!r}.") from exc

        # sockaddr[0] is the address string; strip a zone index like 'fe80::1%eth0'
        addresses = [ipaddress.ip_address(sockaddr[0].split("%")[0]) for _, _, _, _, sockaddr in addrinfo]

    for address in addresses:
        # unwrap ipv4-mapped ipv6 addresses (::ffff:10.0.0.1) so the ipv4 ranges apply
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped

        if (address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified):
            log.debug("URL %r resolves to internal address %s; refusing to request it", url, address)
            raise InternalAddressError(trace, str(address))


def _validate_url(url: str, trace: list[str], *, is_redirect_target: bool = False) -> str:
    """Validate that a url is parsable, uses an allowed scheme, has a hostname
    and does not point to an internal network address.

    Args:
        url: The url to validate.
        trace: The redirect trace discovered so far (used for error reporting).
        is_redirect_target: True if the url came from a Location header instead of the caller.

    Returns:
        The validated url.

    Raises:
        InvalidUrlError: If the url is unparsable, uses a forbidden scheme or has no hostname.
        RedirectTrackerError: If the hostname cannot be resolved.
        InternalAddressError: If the url resolves to an internal address.
    """
    kind = "Redirect target" if is_redirect_target else "Url"
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
    except ValueError as exc:
        raise InvalidUrlError(f"{kind} {url!r} is not a parsable url.") from exc

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise InvalidUrlError(f"{kind} {url!r} does not use one of the allowed schemes {_ALLOWED_SCHEMES}.")
    if not hostname:
        raise InvalidUrlError(f"{kind} {url!r} has no hostname.")

    _require_public_addresses(url, hostname, trace)
    return url


def get_trace(url: str) -> list[str] | None:
    """Get the full redirect trace from the passed URL, including the final destination.
        Args:
            url: The URL to get the trace of.

        Returns:
            All URLs the passed URL redirects through, in order, ending with the
            final destination. The passed URL itself is not included, so the
            list is empty if the passed URL does not redirect.

        Raises:
            ValueError: If the passed URL is None or an empty string.
            RedirectTrackerError: If tracking the redirects fails.
            InvalidUrlError: If the passed URL is invalid.
            InternalAddressError: If the passed URL or a redirect target resolves to an internal address.
            MaxRedirectDepthError: If finding the destination of the passed URL takes more redirects than the max depth.
            LoopingRedirectError: If a redirect loop is encountered while finding the destination.
    """
    # validate input
    if url is None or not url.strip():
        raise ValueError("Url cannot be None or empty.")
    url = _validate_url(url.strip(), [])

    # initialize variables
    log.debug("Tracking redirects of %r", url)
    trace: list[str] = []  # redirect targets only, the passed url is not included
    visited = [url]        # every requested url, used for loop detection
    depth = 0

    with requests.Session() as session:
        # loop (follow redirects hop by hop)
        while True:
            # stream=True so the (possibly huge or malicious) response body is never downloaded, only the status and headers are needed
            try:
                response = session.get(url, allow_redirects=False, stream=True, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                raise RedirectTrackerError(f"Request to {url!r} failed ({type(exc).__name__}).") from exc

            try:
                status = response.status_code
                location = response.headers.get("Location", "").strip()
            finally:
                response.close()

            # check if the chain ends here
            if status not in _REDIRECT_STATUS_CODES:
                log.debug("URL %r answered with status %d; end of redirect chain", url, status)
                break
            if not location:
                log.debug("URL %r answered with status %d but no Location header; treating it as the destination", url, status)
                break

            # the Location header may be relative, resolve it against the current url;
            next_url = urllib.parse.urljoin(url, location)
            trace.append(next_url)

            # check if exceeding max depth
            if depth >= MAX_DEPTH:
                raise MaxRedirectDepthError(trace)

            # check if the target was already visited -> loop
            if next_url in visited:
                raise LoopingRedirectError(trace)

            # validate last, so no dns lookup is done for targets rejected above
            _validate_url(next_url, trace, is_redirect_target=True)

            visited.append(next_url)
            url = next_url
            depth += 1
            log.debug("Followed redirect %d to %r (status %d)", depth, url, status)

    log.debug("Traced %r to %r after %d redirect(s)", visited[0], url, depth)
    return trace


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
            InternalAddressError: If the passed URL or a redirect target resolves to an internal address.
            MaxRedirectDepthError: If finding the destination of the passed URL takes more redirects than the max depth.
            LoopingRedirectError: If a redirect loop is encountered while finding the destination.
    """
    trace = get_trace(url)
    if trace:
        return trace[-1]
    else:
        return None
