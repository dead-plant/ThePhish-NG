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
from pathlib import Path
from typing import Callable

from imapclient import IMAPClient

import utils.config

log = logging.getLogger(Path(__file__).stem)


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
            raise ValueError("max_size must be >= 1")
        self._factory = factory
        self._acquire_timeout = acquire_timeout
        self._idle: queue.LifoQueue[IMAPClient] = queue.LifoQueue(maxsize=max_size)
        self._slots = threading.BoundedSemaphore(max_size)
        self._closed = False
        self._lock = threading.Lock()  # guards _closed during close()

    @contextmanager
    def connection(self):
        """Check out a connection. Returns it to the pool on clean exit, discards it if the block raised."""
        conn = self._acquire()
        try:
            conn.select_folder(utils.config.get()["imap"]["folder"])
            yield conn
        except Exception:
            self._discard(conn)
            raise
        else:
            self._release(conn)

    def close(self) -> None:
        """Close the pool and all idle connections. Connections currently checked out remain open until returned/discarded."""
        with self._lock:
            self._closed = True
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                break
            self._safe_logout(conn)

    # -- internals -----------------------------------------------------

    def _acquire(self) -> IMAPClient:
        if self._closed:
            raise PoolClosedError("connection pool is closed")

        if not self._slots.acquire(timeout=self._acquire_timeout):
            raise PoolTimeoutError(f"no IMAP connection available within {self._acquire_timeout}s")

        try:
            # Reuse an idle connection
            while True:
                try:
                    conn = self._idle.get_nowait()
                except queue.Empty:
                    break
                if self._is_alive(conn):
                    return conn
                log.info("Discarding stale IMAP connection")
                self._safe_logout(conn)

            # Nothing idle, open a fresh connection
            return self._factory()
        except BaseException:
            self._slots.release()
            raise

    def _release(self, conn: IMAPClient) -> None:
        if self._closed:
            self._safe_logout(conn)
            self._slots.release()
            return
        try:
            self._idle.put_nowait(conn)
        except queue.Full:
            # Shouldn't happen, but be safe
            self._safe_logout(conn)
        finally:
            self._slots.release()

    def _discard(self, conn: IMAPClient) -> None:
        self._safe_logout(conn)
        self._slots.release()

    @staticmethod
    def _is_alive(conn: IMAPClient) -> bool:
        try:
            conn.noop()
            return True
        except Exception:
            return False

    @staticmethod
    def _safe_logout(conn: IMAPClient) -> None:
        try:
            conn.logout()
        except Exception:
            try:
                conn.shutdown()
            except Exception:
                pass


# Connection Factory
def create_connection() -> IMAPClient:
    """Open, secure and authenticate a single IMAPClient connection
    based on the [imap] section of the application config."""
    config = utils.config.get()
    imap = config["imap"]

    host = imap["host"]
    port = imap["port"]
    tls = imap["tls"]
    insecure = imap["tlsinsecure"]
    user = imap["user"]
    pwd = imap["password"]

    if insecure == "no":
        ctx = ssl.create_default_context()
    elif insecure == "yes":
        ctx = ssl._create_unverified_context()
    else:
        raise ValueError("imap.tlsinsecure must be 'yes' or 'no'")

    if tls == "tls":
        conn = IMAPClient(host, port=port, ssl=True, ssl_context=ctx, timeout=5)
    elif tls == "starttls":
        conn = IMAPClient(host, port=port, ssl=False, timeout=5)
        conn.starttls(ssl_context=ctx)
    elif tls == "none":
        conn = IMAPClient(host, port=port, ssl=False, timeout=5)
    else:
        raise ValueError("imap.tls must be 'tls', 'starttls' or 'none'")

    conn.login(user, pwd)
    log.info("Connected to %s@%s:%s/%s (tls=%s, insecure=%s)",user, host, port, imap["folder"], tls, insecure,)
    return conn


# Module-level singleton, created lazily on first use.
_pool: IMAPConnectionPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> IMAPConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = IMAPConnectionPool(factory=create_connection, max_size=5)
    return _pool
