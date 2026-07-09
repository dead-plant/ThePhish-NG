import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast
from unittest.mock import patch

from imapclient import IMAPClient

from app.repositories import imap_pool


BASE_IMAP_CONFIG: dict[str, object] = {
    "host": "imap.example.test",
    "port": 993,
    "tls_mode": "tls",
    "tls_insecure": "no",
    "user": "analyst@example.test",
    "password": "correct horse battery staple",
    "folder": "INBOX",
}


def app_config(**imap_overrides: object) -> dict[str, dict[str, object]]:
    imap_config = {**BASE_IMAP_CONFIG, **imap_overrides}
    return {"imap": imap_config}


def as_imap_client(conn: "FakeIMAPConnection") -> IMAPClient:
    return cast(IMAPClient, conn)


class FakeIMAPConnection:
    def __init__(self, name: str):
        self.name = name
        self.noop_calls = 0
        self.select_folder_calls: list[str] = []
        self.logout_calls = 0
        self.shutdown_calls = 0
        self.starttls_contexts: list[object] = []
        self.login_calls: list[tuple[str, str]] = []
        self.noop_error: BaseException | None = None
        self.select_folder_error: BaseException | None = None
        self.logout_error: BaseException | None = None
        self.shutdown_error: BaseException | None = None
        self.starttls_error: BaseException | None = None
        self.login_error: BaseException | None = None

    def noop(self) -> None:
        self.noop_calls += 1
        if self.noop_error is not None:
            raise self.noop_error

    def select_folder(self, folder: str) -> None:
        self.select_folder_calls.append(folder)
        if self.select_folder_error is not None:
            raise self.select_folder_error

    def logout(self) -> None:
        self.logout_calls += 1
        if self.logout_error is not None:
            raise self.logout_error

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.shutdown_error is not None:
            raise self.shutdown_error

    def starttls(self, ssl_context: object) -> None:
        self.starttls_contexts.append(ssl_context)
        if self.starttls_error is not None:
            raise self.starttls_error

    def login(self, user: str, password: str) -> None:
        self.login_calls.append((user, password))
        if self.login_error is not None:
            raise self.login_error

    @property
    def was_closed(self) -> bool:
        return self.logout_calls > 0 or self.shutdown_calls > 0


FactoryResult = FakeIMAPConnection | BaseException


class SequenceFactory:
    def __init__(self, results: list[FactoryResult]):
        self._results = list(results)
        self.call_count = 0

    def __call__(self) -> IMAPClient:
        self.call_count += 1
        if not self._results:
            raise AssertionError("factory called more times than expected")
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return as_imap_client(result)


class FakeUnavailableSemaphore:
    def __init__(self):
        self.acquire_timeout: float | None = None
        self.release_count = 0

    def acquire(self, timeout: float | None = None) -> bool:
        self.acquire_timeout = timeout
        return False

    def release(self) -> None:
        self.release_count += 1


class FakeContextFactory:
    def __init__(self, context: object):
        self.context = context
        self.call_count = 0

    def __call__(self) -> object:
        self.call_count += 1
        return self.context


class FakeIMAPClientConstructor:
    def __init__(self, result: FactoryResult):
        self.result = result
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> IMAPClient:
        self.calls.append((args, kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
        return as_imap_client(self.result)


@contextmanager
def patched_app_config(**imap_overrides: object) -> Iterator[None]:
    with patch.object(imap_pool.config, "get_app_config", return_value=app_config(**imap_overrides)):
        yield


@contextmanager
def patched_connection_dependencies(
    client_result: FactoryResult,
    **imap_overrides: object,
) -> Iterator[tuple[FakeIMAPClientConstructor, object, object, FakeContextFactory, FakeContextFactory]]:
    verified_context = object()
    unverified_context = object()
    imap_client = FakeIMAPClientConstructor(client_result)
    verified_context_factory = FakeContextFactory(verified_context)
    unverified_context_factory = FakeContextFactory(unverified_context)

    with patch.object(imap_pool.config, "get_app_config", return_value=app_config(**imap_overrides)):
        with patch.object(imap_pool, "IMAPClient", new=cast(Any, imap_client)):
            with patch.object(imap_pool.ssl, "create_default_context", new=cast(Any, verified_context_factory)):
                with patch.object(imap_pool.ssl, "_create_unverified_context", new=cast(Any, unverified_context_factory)):
                    yield (
                        imap_client,
                        verified_context,
                        unverified_context,
                        verified_context_factory,
                        unverified_context_factory,
                    )


class IMAPConnectionPoolTests(unittest.TestCase):
    def test_connection_selects_configured_folder_and_reuses_healthy_connection(self):
        conn = FakeIMAPConnection("conn")
        factory = SequenceFactory([conn])
        pool = imap_pool.IMAPConnectionPool(factory=factory, max_size=2, acquire_timeout=1)

        with patched_app_config(folder="Phishing"):
            with pool.connection() as checked_out:
                self.assertIs(checked_out, conn)

            with pool.connection() as checked_out:
                self.assertIs(checked_out, conn)

        self.assertEqual(factory.call_count, 1)
        self.assertEqual(conn.noop_calls, 1)
        self.assertEqual(conn.select_folder_calls, ["Phishing", "Phishing"])
        self.assertEqual(conn.logout_calls, 0)

    def test_idle_connections_are_reused_in_lifo_order(self):
        first = FakeIMAPConnection("first")
        second = FakeIMAPConnection("second")
        factory = SequenceFactory([first, second])
        pool = imap_pool.IMAPConnectionPool(factory=factory, max_size=2, acquire_timeout=1)

        with patched_app_config():
            first_context = pool.connection()
            checked_out_first = first_context.__enter__()
            second_context = pool.connection()
            checked_out_second = second_context.__enter__()

            self.assertIs(checked_out_first, first)
            self.assertIs(checked_out_second, second)

            first_context.__exit__(None, None, None)
            second_context.__exit__(None, None, None)

            with pool.connection() as reused:
                self.assertIs(reused, second)

        self.assertEqual(factory.call_count, 2)
        self.assertEqual(second.noop_calls, 1)
        self.assertEqual(first.noop_calls, 0)

    def test_connection_is_discarded_when_user_block_raises(self):
        broken = FakeIMAPConnection("broken")
        fresh = FakeIMAPConnection("fresh")
        factory = SequenceFactory([broken, fresh])
        pool = imap_pool.IMAPConnectionPool(factory=factory, max_size=1, acquire_timeout=1)

        with patched_app_config():
            with self.assertRaisesRegex(RuntimeError, "analysis failed"):
                with pool.connection():
                    raise RuntimeError("analysis failed")

            with pool.connection() as checked_out:
                self.assertIs(checked_out, fresh)

        self.assertEqual(broken.logout_calls, 1)
        self.assertEqual(broken.noop_calls, 0)
        self.assertEqual(factory.call_count, 2)

    def test_connection_is_discarded_when_folder_selection_fails(self):
        broken = FakeIMAPConnection("broken")
        broken.select_folder_error = RuntimeError("missing folder")
        fresh = FakeIMAPConnection("fresh")
        factory = SequenceFactory([broken, fresh])
        pool = imap_pool.IMAPConnectionPool(factory=factory, max_size=1, acquire_timeout=1)

        with patched_app_config(folder="Quarantine"):
            with self.assertRaisesRegex(RuntimeError, "missing folder"):
                with pool.connection():
                    pass

            with pool.connection() as checked_out:
                self.assertIs(checked_out, fresh)

        self.assertEqual(broken.logout_calls, 1)
        self.assertEqual(fresh.select_folder_calls, ["Quarantine"])

    def test_stale_idle_connection_is_closed_and_replaced(self):
        stale = FakeIMAPConnection("stale")
        replacement = FakeIMAPConnection("replacement")
        factory = SequenceFactory([stale, replacement])
        pool = imap_pool.IMAPConnectionPool(factory=factory, max_size=1, acquire_timeout=1)

        with patched_app_config():
            with pool.connection() as checked_out:
                self.assertIs(checked_out, stale)

            stale.noop_error = OSError("socket closed")

            with pool.connection() as checked_out:
                self.assertIs(checked_out, replacement)

        self.assertEqual(stale.noop_calls, 1)
        self.assertEqual(stale.logout_calls, 1)
        self.assertEqual(replacement.select_folder_calls, ["INBOX"])
        self.assertEqual(factory.call_count, 2)

    def test_factory_failure_does_not_consume_pool_capacity(self):
        conn = FakeIMAPConnection("conn")
        factory = SequenceFactory([OSError("dial failed"), conn])
        pool = imap_pool.IMAPConnectionPool(factory=factory, max_size=1, acquire_timeout=1)

        with self.assertRaisesRegex(OSError, "dial failed"):
            with pool.connection():
                pass

        with patched_app_config():
            with pool.connection() as checked_out:
                self.assertIs(checked_out, conn)

        self.assertEqual(factory.call_count, 2)
        self.assertEqual(conn.select_folder_calls, ["INBOX"])

    def test_timeout_while_pool_is_exhausted_raises_without_creating_connection(self):
        factory = SequenceFactory([])
        pool = imap_pool.IMAPConnectionPool(factory=factory, max_size=1, acquire_timeout=1)
        unavailable = FakeUnavailableSemaphore()
        setattr(pool, "_slots", unavailable)

        with self.assertRaises(imap_pool.PoolTimeoutError):
            with pool.connection():
                pass

        self.assertEqual(unavailable.acquire_timeout, 1)
        self.assertEqual(unavailable.release_count, 0)
        self.assertEqual(factory.call_count, 0)

    def test_close_logs_out_idle_connections_and_rejects_new_checkouts(self):
        conn = FakeIMAPConnection("conn")
        factory = SequenceFactory([conn])
        pool = imap_pool.IMAPConnectionPool(factory=factory, max_size=1, acquire_timeout=1)

        with patched_app_config():
            with pool.connection():
                pass

        pool.close()
        pool.close()

        self.assertEqual(conn.logout_calls, 1)
        with self.assertRaises(imap_pool.PoolClosedError):
            with pool.connection():
                pass

    def test_connection_returned_after_close_is_logged_out_not_reused(self):
        conn = FakeIMAPConnection("conn")
        factory = SequenceFactory([conn])
        pool = imap_pool.IMAPConnectionPool(factory=factory, max_size=1, acquire_timeout=1)

        with patched_app_config():
            checked_out_context = pool.connection()
            self.assertIs(checked_out_context.__enter__(), conn)
            pool.close()
            checked_out_context.__exit__(None, None, None)

        self.assertEqual(conn.logout_calls, 1)
        with self.assertRaises(imap_pool.PoolClosedError):
            with pool.connection():
                pass

    def test_safe_logout_falls_back_to_shutdown_and_never_raises(self):
        conn = FakeIMAPConnection("conn")
        conn.logout_error = RuntimeError("logout failed")

        imap_pool.IMAPConnectionPool._safe_logout(as_imap_client(conn))

        self.assertEqual(conn.logout_calls, 1)
        self.assertEqual(conn.shutdown_calls, 1)

    def test_constructor_rejects_invalid_pool_settings(self):
        valid_factory = SequenceFactory([])
        invalid_cases: list[tuple[object, int, float, type[BaseException]]] = [
            (None, 1, 1, TypeError),
            (object(), 1, 1, TypeError),
            (valid_factory, 0, 1, ValueError),
            (valid_factory, -1, 1, ValueError),
            (valid_factory, 1, 0, ValueError),
            (valid_factory, 1, 121, ValueError),
        ]

        for factory, max_size, acquire_timeout, expected_error in invalid_cases:
            with self.subTest(factory=factory, max_size=max_size, acquire_timeout=acquire_timeout):
                with self.assertRaises(expected_error):
                    imap_pool.IMAPConnectionPool(
                        factory=cast(Any, factory),
                        max_size=max_size,
                        acquire_timeout=acquire_timeout,
                    )


class CreateConnectionTests(unittest.TestCase):
    def test_create_connection_opens_and_logs_in_for_each_supported_tls_mode(self):
        cases: list[dict[str, object]] = [
            {
                "tls_mode": "tls",
                "tls_insecure": "no",
                "expected_client_kwargs": {
                    "port": 993,
                    "ssl": True,
                    "timeout": 5,
                },
                "starts_tls": False,
                "uses_verified_context": True,
            },
            {
                "tls_mode": "starttls",
                "tls_insecure": "yes",
                "expected_client_kwargs": {"port": 993, "ssl": False, "timeout": 5},
                "starts_tls": True,
                "uses_verified_context": False,
            },
            {
                "tls_mode": "none",
                "tls_insecure": "no",
                "expected_client_kwargs": {"port": 993, "ssl": False, "timeout": 5},
                "starts_tls": False,
                "uses_verified_context": True,
            },
        ]

        for case in cases:
            tls_mode = str(case["tls_mode"])
            tls_insecure = str(case["tls_insecure"])
            with self.subTest(tls_mode=tls_mode, tls_insecure=tls_insecure):
                conn = FakeIMAPConnection("conn")
                with patched_connection_dependencies(
                    conn,
                    tls_mode=tls_mode,
                    tls_insecure=tls_insecure,
                ) as (
                    imap_client,
                    verified_context,
                    unverified_context,
                    _verified_context_factory,
                    _unverified_context_factory,
                ):
                    result = imap_pool.create_connection()

                self.assertIs(result, conn)
                self.assertEqual(len(imap_client.calls), 1)
                args, kwargs = imap_client.calls[0]
                self.assertEqual(args, ("imap.example.test",))

                expected_kwargs = dict(cast(dict[str, object], case["expected_client_kwargs"]))
                if tls_mode == "tls":
                    expected_kwargs["ssl_context"] = verified_context
                self.assertEqual(kwargs, expected_kwargs)

                if bool(case["starts_tls"]):
                    expected_context = verified_context if bool(case["uses_verified_context"]) else unverified_context
                    self.assertEqual(conn.starttls_contexts, [expected_context])
                else:
                    self.assertEqual(conn.starttls_contexts, [])
                self.assertEqual(conn.login_calls, [("analyst@example.test", "correct horse battery staple")])

    def test_create_connection_rejects_invalid_tls_verification_setting(self):
        conn = FakeIMAPConnection("conn")

        with patched_connection_dependencies(conn, tls_insecure="maybe") as (
            imap_client,
            _verified_context,
            _unverified_context,
            verified_context_factory,
            unverified_context_factory,
        ):
            with self.assertRaises(ValueError):
                imap_pool.create_connection()

        self.assertEqual(verified_context_factory.call_count, 0)
        self.assertEqual(unverified_context_factory.call_count, 0)
        self.assertEqual(imap_client.calls, [])

    def test_create_connection_rejects_invalid_tls_mode(self):
        conn = FakeIMAPConnection("conn")

        with patched_connection_dependencies(conn, tls_mode="implicit-starttls") as (
            imap_client,
            _verified_context,
            _unverified_context,
            _verified_context_factory,
            _unverified_context_factory,
        ):
            with self.assertRaises(ValueError):
                imap_pool.create_connection()

        self.assertEqual(imap_client.calls, [])

    def test_create_connection_wraps_socket_open_failures(self):
        with patched_connection_dependencies(OSError("connection refused")):
            with self.assertRaises(imap_pool.IMAPConnectionError):
                imap_pool.create_connection()

    def test_create_connection_closes_partially_opened_connection_when_starttls_fails(self):
        conn = FakeIMAPConnection("conn")
        conn.starttls_error = OSError("STARTTLS failed")

        with patched_connection_dependencies(conn, tls_mode="starttls"):
            with self.assertRaises(imap_pool.IMAPConnectionError):
                imap_pool.create_connection()

        self.assertTrue(conn.was_closed)
        self.assertEqual(conn.login_calls, [])

    def test_create_connection_closes_connection_when_login_fails(self):
        conn = FakeIMAPConnection("conn")
        conn.login_error = RuntimeError("bad credentials")

        with patched_connection_dependencies(conn):
            with self.assertRaises(imap_pool.IMAPLoginError):
                imap_pool.create_connection()

        self.assertTrue(conn.was_closed)


if __name__ == "__main__":
    unittest.main()
