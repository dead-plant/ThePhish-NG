"""Thread-safe connection pool for IMAPClient connections.

Usage:
    with pool.connection() as conn:
        conn.search(["UNSEEN"])
"""

import logging
import queue
import ssl
import threading
from contextlib import contextmanager
from typing import Callable
from imapclient import IMAPClient
from app.utils import config as config_utils

log = logging.getLogger(__name__)

class PoolClosedError(Exception):
    """Raised when acquiring from a pool that has been closed."""


class PoolTimeoutError(Exception):
    """Raised when no connection becomes available within the timeout."""


class IMAPConnectionPool:
    """A bounded pool of IMAPClient connections.

    - LIFO reuse
    - Validate on use (NOOP on checkout)
    - A semaphore bounds the total number of live connections to max_size.
    """

    def __init__(self, factory: Callable[[], IMAPClient], max_size: int = 5, acquire_timeout: float = 15.0):
        if max_size < 1:
            log.error("Invalid IMAP pool size requested: max_size=%s", max_size)
            raise ValueError("max_size must be >= 1")
        self._factory = factory
        self._acquire_timeout = acquire_timeout
        self._idle: queue.LifoQueue[IMAPClient] = queue.LifoQueue(maxsize=max_size)
        self._slots = threading.BoundedSemaphore(max_size)
        self._closed = False
        self._lock = threading.Lock()  # guards _closed during close()
        log.info("Initialized IMAP connection pool: max_size=%d, acquire_timeout=%ss", max_size, acquire_timeout)

    @contextmanager
    def connection(self):
        """Check out a connection. Returns it to the pool on clean exit, discards it if the block raised."""
        conn = self._acquire()
        try:
            folder = config_utils.get()["imap"]["folder"]
            log.debug("Selecting IMAP folder '%s'", folder)
            conn.select_folder(folder)
            yield conn
        except Exception:
            log.warning("Discarding IMAP connection after failure during use", exc_info=True)
            self._discard(conn)
            raise
        else:
            self._release(conn)

    def close(self) -> None:
        """Close the pool and all idle connections. Connections currently checked out remain open until returned/discarded."""
        with self._lock:
            self._closed = True
        closed_idle = 0
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                break
            self._safe_logout(conn)
            closed_idle += 1
        log.info("Closed IMAP connection pool; idle connections closed=%d", closed_idle)

    # -- internals -----------------------------------------------------

    def _acquire(self) -> IMAPClient:
        if self._closed:
            log.warning("Attempted to acquire IMAP connection from a closed pool")
            raise PoolClosedError("connection pool is closed")

        log.debug("Attempting to acquire IMAP connection; idle_available=%d", self._idle.qsize())
        if not self._slots.acquire(timeout=self._acquire_timeout):
            log.warning("Timed out after %ss waiting for an available IMAP connection", self._acquire_timeout)
            raise PoolTimeoutError(f"no IMAP connection available within {self._acquire_timeout}s")

        try:
            # Reuse an idle connection
            while True:
                try:
                    conn = self._idle.get_nowait()
                except queue.Empty:
                    break
                if self._is_alive(conn):
                    log.debug("Reusing healthy idle IMAP connection")
                    return conn
                log.warning("Discarding stale IMAP connection")
                self._safe_logout(conn)

            # Nothing idle, open a fresh connection
            log.debug("No idle IMAP connection available; opening a new connection")
            return self._factory()
        except BaseException:
            log.error("Failed to acquire IMAP connection", exc_info=True)
            self._slots.release()
            raise

    def _release(self, conn: IMAPClient) -> None:
        if self._closed:
            log.debug("Pool closed while connection was checked out; logging out returned IMAP connection")
            self._safe_logout(conn)
            self._slots.release()
            return
        try:
            self._idle.put_nowait(conn)
            log.debug("Returned IMAP connection to idle pool; idle_available=%d", self._idle.qsize())
        except queue.Full:
            # Shouldn't happen, but be safe
            log.warning("IMAP idle pool is full while releasing a connection, this shouldn't happen; closing the extra connection")
            self._safe_logout(conn)
        finally:
            self._slots.release()

    def _discard(self, conn: IMAPClient) -> None:
        log.debug("Discarding IMAP connection")
        self._safe_logout(conn)
        self._slots.release()

    def _is_alive(self, conn: IMAPClient) -> bool:
        try:
            conn.noop()
            return True
        except Exception as e:
            log.debug("IMAP connection health check failed: %s", e)
            return False

    @staticmethod
    def _safe_logout(conn: IMAPClient) -> None:
        try:
            conn.logout()
            log.debug("Logged out IMAP connection")
        except Exception:
            log.debug("IMAP logout failed; attempting socket shutdown", exc_info=True)
            try:
                conn.shutdown()
                log.debug("Shutdown IMAP connection after logout failure")
            except Exception:
                log.warning("Failed to close IMAP connection cleanly", exc_info=True)


# Connection Factory
def create_connection() -> IMAPClient:
    """Open, secure and authenticate a single IMAPClient connection
    based on the [imap] section of the application config."""
    config = config_utils.get()
    imap = config["imap"]

    host = imap["host"]
    port = imap["port"]
    tls = imap["tls"]
    insecure = imap["tlsinsecure"]
    user = imap["user"]
    pwd = imap["password"]

    if insecure == "no":
        ctx = ssl.create_default_context()
        log.debug("Created verified TLS context for IMAP connection")
    elif insecure == "yes":
        ctx = ssl._create_unverified_context()
        log.warning("Creating IMAP connection with TLS certificate verification disabled")
    else:
        log.error("Invalid IMAP TLS verification setting: imap.tlsinsecure=%s", insecure)
        raise ValueError("imap.tlsinsecure must be 'yes' or 'no'")

    log.debug("Opening IMAP connection to %s:%s with tls=%s", host, port, tls)
    if tls == "tls":
        conn = IMAPClient(host, port=port, ssl=True, ssl_context=ctx, timeout=5)
    elif tls == "starttls":
        conn = IMAPClient(host, port=port, ssl=False, timeout=5)
        conn.starttls(ssl_context=ctx)
    elif tls == "none":
        conn = IMAPClient(host, port=port, ssl=False, timeout=5)
    else:
        log.error("Invalid IMAP TLS mode: imap.tls=%s", tls)
        raise ValueError("imap.tls must be 'tls', 'starttls' or 'none'")

    log.debug("Authenticating IMAP user '%s' against %s:%s", user, host, port)
    conn.login(user, pwd)
    log.info("Connected to %s@%s:%s/%s (tls=%s, insecure=%s)",user, host, port, imap["folder"], tls, insecure,)
    return conn


# Module-level singleton, created lazily on first use.
_pool: IMAPConnectionPool
_pool_lock = threading.Lock()


def get_pool() -> IMAPConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                log.debug("Creating module-level IMAP connection pool")
                _pool = IMAPConnectionPool(factory=create_connection, max_size=5)
    else:
        log.debug("Returning existing module-level IMAP connection pool")
    return _pool
