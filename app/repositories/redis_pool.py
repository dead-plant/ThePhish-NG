"""Shared Redis connection pool and key namespace.

A single redis-py client backed by a bounded, thread-safe connection pool,
created from the [redis] section of the application config. Connections are
opened lazily on first use; failing commands raise redis.RedisError subclasses.

All responses are decoded to str (decode_responses=True).

Usage:
    from app.repositories import redis_pool

    client = redis_pool.get_client()
    client.set(redis_pool.key("analysis", case_id), payload)
"""

import logging
from typing import Final

import redis

from app import config

log = logging.getLogger(__name__)

# Pool sizing and timeouts. When all connections are in use, a caller blocks
# for up to ACQUIRE_TIMEOUT seconds, then redis-py raises a ConnectionError.
MAX_CONNECTIONS = 10
ACQUIRE_TIMEOUT = 15  # seconds
SOCKET_TIMEOUT = 5  # seconds, applies to connect and to each command
HEALTH_CHECK_INTERVAL = 30  # seconds a connection may idle before it is pinged on reuse

# create the shared redis connection pool and client
try:
    redis_config = config.get_app_config()["redis"]
    url = redis_config["url"]
    key_prefix = redis_config["key_prefix"]

    if not isinstance(url, str) or not url.strip():
        raise ValueError("redis.url must be a non-empty string")
    if not isinstance(key_prefix, str) or not key_prefix.strip():
        raise ValueError("redis.key_prefix must be a non-empty string")

    _key_prefix: Final[str] = key_prefix
    _pool: Final = redis.BlockingConnectionPool.from_url(
        url,
        max_connections=MAX_CONNECTIONS,
        timeout=ACQUIRE_TIMEOUT,
        socket_connect_timeout=SOCKET_TIMEOUT,
        socket_timeout=SOCKET_TIMEOUT,
        health_check_interval=HEALTH_CHECK_INTERVAL,
        decode_responses=True,
    )
    _client: Final = redis.Redis(connection_pool=_pool)
    log.info("Created Redis connection pool (max_connections=%d, key_prefix=%r)", MAX_CONNECTIONS, _key_prefix)
except Exception as exc:
    log.error("Failed to create Redis connection pool", exc_info=exc)
    raise exc


def get_client() -> redis.Redis:
    """Return the shared Redis client. Safe to use from multiple threads."""
    return _client


def key(*parts: str) -> str:
    """Build a namespaced Redis key: '<key_prefix>:<part>[:<part>...]'.

    Args:
        parts: One or more key segments, e.g. key("analysis", case_id).

    Returns:
        The full key including the configured prefix.
    """
    if not parts:
        raise ValueError("at least one key part is required")
    if not all(isinstance(part, str) and part.strip() for part in parts):
        raise ValueError("key parts must be non-empty strings")
    return ":".join((_key_prefix, *parts))


def close() -> None:
    """Close the shared client and disconnect all pooled connections."""
    _client.close()
    _pool.disconnect()
    log.info("Closed Redis connection pool")
