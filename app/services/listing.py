"""Application services for listing resources exposed by the API."""

import logging
from dataclasses import asdict
from app.repositories.imap_pool import IMAPLoginError, IMAPConnectionError, PoolTimeoutError, PoolClosedError

from app.repositories import mailbox

log = logging.getLogger(__name__)


class ListEmailsError(RuntimeError):
    """Raised when a resource cannot be listed."""


class ImapConnectionError(ListEmailsError):
    """Raised when listing fails because the IMAP mailbox is unavailable."""


def list_emails() -> list[dict[str, object]]:
    try:
        messages = mailbox.list_analyzable()
        listed_emails = [asdict(message) for message in messages]

    except (IMAPLoginError, IMAPConnectionError, PoolTimeoutError, PoolClosedError) as exc:
        raise ImapConnectionError("IMAP connection failed") from exc
    except Exception as exc:
        raise ListEmailsError("Failed to list analyzable emails") from exc

    log.debug("Prepared %d email(s) for listing", len(listed_emails))
    return listed_emails
