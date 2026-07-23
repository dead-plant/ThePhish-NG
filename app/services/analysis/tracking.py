"""Analysis state and progress tracking backed by Redis.

The Redis state hash is the source of truth for an analysis. The per-analysis
log is persisted as a Redis list, and live updates are published on a pub/sub
channel so SSE clients can follow along; a missed pub/sub event never
invalidates the state, because streaming re-checks the stored state.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

import ioc_fanger
import redis

from app import config
from app.repositories import redis_pool
from app.services.analysis.errors import AnalysisNotFoundError, AnalysisStorageError

log = logging.getLogger(__name__)

# Analysis lifecycle states
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
TERMINAL_STATUSES = frozenset({STATUS_FINISHED, STATUS_FAILED})

# State hash fields exposed to API consumers, in serialization order.
STATE_FIELDS = ("analysis_id", "mail_uid", "status", "created_at", "started_at", "finished_at", "case_id", "case_number", "verdict", "error")

# SSE stream tuning: how often to poll pub/sub, send keepalives and re-check
# the stored state (the latter guards against missed pub/sub events).
PUBSUB_POLL_TIMEOUT = 1.0  # seconds
KEEPALIVE_INTERVAL = 15.0  # seconds
STATE_CHECK_INTERVAL = 5.0  # seconds


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with timezone."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _retention_seconds() -> int:
    return int(config.get_app_config()["analysis"]["retention_days"]) * 86400


def _state_key(analysis_id: str) -> str:
    return redis_pool.key("analysis", analysis_id)


def _log_key(analysis_id: str) -> str:
    return redis_pool.key("analysis", analysis_id, "log")


def _channel(analysis_id: str) -> str:
    return redis_pool.key("analysis", analysis_id, "events")


def _publish_event(analysis_id: str, event: dict) -> None:
    """Publish a live event, best-effort: state was already saved, so a missed
    pub/sub update must not fail the caller."""
    try:
        redis_pool.get_client().publish(_channel(analysis_id), json.dumps(event))
    except redis.RedisError as exc:
        log.warning("Could not publish %s event for analysis %s (%s)", event.get("type"), analysis_id, type(exc).__name__)


def _status_event(state: dict) -> dict:
    """Build a status event from a state dict, omitting empty optional fields."""
    event = {"type": "status", "status": state.get("status")}
    for field in ("verdict", "case_id", "case_number", "error"):
        if state.get(field):
            event[field] = state[field]
    return event


# --- State ----------------------------------------------------------------
def create_analysis(analysis_id: str, mail_uid: int) -> dict:
    """Store the initial state of a new analysis.

    Returns:
        The initial state dict.

    Raises:
        AnalysisStorageError: If the state cannot be written to Redis.
    """
    state = {
        "analysis_id": analysis_id,
        "mail_uid": str(mail_uid),
        "status": STATUS_PENDING,
        "created_at": utc_now_iso(),
    }
    try:
        pipe = redis_pool.get_client().pipeline()
        pipe.hset(_state_key(analysis_id), mapping=state)
        pipe.expire(_state_key(analysis_id), _retention_seconds())
        pipe.execute()
    except redis.RedisError as exc:
        raise AnalysisStorageError("Could not store the initial analysis state") from exc
    log.info("Created analysis %s for mail UID %d", analysis_id, mail_uid)
    return _deserialize_state(state)


def set_state_fields(analysis_id: str, *, publish: bool = True, **fields: str) -> None:
    """Update fields of the analysis state and publish a status event.

    Raises:
        AnalysisStorageError: If the state cannot be written to Redis.
    """
    try:
        pipe = redis_pool.get_client().pipeline()
        pipe.hset(_state_key(analysis_id), mapping=fields)
        pipe.expire(_state_key(analysis_id), _retention_seconds())
        pipe.hgetall(_state_key(analysis_id))
        results = pipe.execute()
    except redis.RedisError as exc:
        raise AnalysisStorageError("Could not update the analysis state") from exc

    if publish:
        _publish_event(analysis_id, _status_event(results[-1]))


def mark_failed(analysis_id: str, error: str) -> None:
    """Mark an analysis as failed with an error message, best-effort."""
    try:
        set_state_fields(analysis_id, status=STATUS_FAILED, error=error, finished_at=utc_now_iso())
    except AnalysisStorageError as exc:
        log.error("Could not mark analysis %s as failed", analysis_id, exc_info=exc)


def _deserialize_state(raw: dict) -> dict:
    """Convert a raw Redis state hash into the API representation, dropping
    empty optional fields."""
    state = {field: raw[field] for field in STATE_FIELDS if raw.get(field)}
    if "mail_uid" in state:
        state["mail_uid"] = int(state["mail_uid"])
    return state


def get_analysis(analysis_id: str) -> dict:
    """Return the current state of an analysis.

    Raises:
        AnalysisNotFoundError: If the analysis does not exist or has expired.
        AnalysisStorageError: If the state cannot be read from Redis.
    """
    if not isinstance(analysis_id, str) or not analysis_id.strip():
        raise AnalysisNotFoundError("Analysis id must be a non-empty string")
    try:
        raw = redis_pool.get_client().hgetall(_state_key(analysis_id))
    except redis.RedisError as exc:
        raise AnalysisStorageError("Could not read the analysis state") from exc
    if not raw:
        raise AnalysisNotFoundError(f"Analysis {analysis_id} does not exist or has expired")
    return _deserialize_state(raw)


# --- Log ------------------------------------------------------------------
def _entry_with_seq(index: int, raw: str) -> dict:
    entry = json.loads(raw)
    entry["seq"] = index
    return entry


def append_log_entry(analysis_id: str, level: str, message: str) -> dict:
    """Append an entry to the persisted analysis log and publish it.

    Returns:
        The appended entry including its sequence number.

    Raises:
        AnalysisStorageError: If the entry cannot be written to Redis.
    """
    entry = {"timestamp": utc_now_iso(), "level": level, "message": message}
    try:
        pipe = redis_pool.get_client().pipeline()
        pipe.rpush(_log_key(analysis_id), json.dumps(entry))
        pipe.expire(_log_key(analysis_id), _retention_seconds())
        results = pipe.execute()
    except redis.RedisError as exc:
        raise AnalysisStorageError("Could not append to the analysis log") from exc

    entry["seq"] = results[0] - 1  # rpush returns the new list length
    _publish_event(analysis_id, {"type": "log", **entry})
    return entry


def get_analysis_log(analysis_id: str, start: int = 0) -> list[dict]:
    """Return the stored log entries of an analysis in chronological order.

    Args:
        analysis_id: Id of the analysis.
        start: First sequence number to return (for incremental reads).

    Raises:
        AnalysisNotFoundError: If the analysis does not exist or has expired.
        AnalysisStorageError: If the log cannot be read from Redis.
    """
    get_analysis(analysis_id)  # not-found / storage validation
    try:
        raw_entries = redis_pool.get_client().lrange(_log_key(analysis_id), start, -1)
    except redis.RedisError as exc:
        raise AnalysisStorageError("Could not read the analysis log") from exc
    return [_entry_with_seq(start + offset, raw) for offset, raw in enumerate(raw_entries)]


class AnalysisLogger:
    """Structured per-analysis logger.

    Entries are persisted in Redis and mirrored in memory, so the complete log
    stays available for the result email even if individual Redis writes fail.

    Messages are defanged (hXXp://, [.]) so no URL, domain or address from the
    analyzed email ever appears clickable in the log or in the result email.
    """

    def __init__(self, analysis_id: str) -> None:
        self.analysis_id = analysis_id
        self.entries: list[dict] = []

    def _append(self, level: str, message: str) -> None:
        message = ioc_fanger.defang(message)
        entry = {"timestamp": utc_now_iso(), "level": level, "message": message}
        try:
            entry = append_log_entry(self.analysis_id, level, message)
        except AnalysisStorageError as exc:
            log.warning("Analysis %s log entry only kept in memory (%s)", self.analysis_id, exc)
        self.entries.append(entry)

    def info(self, message: str) -> None:
        self._append("info", message)

    def warning(self, message: str) -> None:
        self._append("warning", message)

    def error(self, message: str) -> None:
        self._append("error", message)

    def snapshot(self) -> list[dict]:
        """Return a copy of all entries recorded so far.

        The in-memory entries are the source, so the snapshot stays complete
        even if individual Redis writes failed.
        """
        return list(self.entries)


# --- SSE streaming ----------------------------------------------------------
def _sse(event: str, data: dict, event_id: Optional[int] = None) -> str:
    lines = [f"event: {event}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


def stream_analysis_events(analysis_id: str) -> Iterator[str]:
    """Return a generator of SSE-formatted analysis events.

    Stored log entries are replayed first, followed by the current status and
    then live pub/sub events. The stream ends cleanly after a terminal state.

    Raises:
        AnalysisNotFoundError: If the analysis does not exist or has expired
            (raised before the first event, so routes can return 404).
        AnalysisStorageError: If the initial state cannot be read from Redis.
    """
    state = get_analysis(analysis_id)  # eager, so a missing analysis raises before streaming starts
    return _event_stream(analysis_id, state)


def _drain_log(analysis_id: str, next_seq: int) -> tuple[list[str], int]:
    """Fetch stored log entries from next_seq on and format them as SSE events."""
    events = []
    for entry in get_analysis_log(analysis_id, start=next_seq):
        events.append(_sse("log", entry, event_id=entry["seq"]))
        next_seq = entry["seq"] + 1
    return events, next_seq


def _event_stream(analysis_id: str, state: dict) -> Iterator[str]:
    pubsub = redis_pool.get_client().pubsub(ignore_subscribe_messages=True)
    try:
        # Subscribe before replaying, so no event between replay and live phase is lost.
        pubsub.subscribe(_channel(analysis_id))

        events, next_seq = _drain_log(analysis_id, 0)
        yield from events
        yield _sse("status", _status_event(state))
        if state["status"] in TERMINAL_STATUSES:
            return

        last_keepalive = last_state_check = time.monotonic()
        while True:
            message = pubsub.get_message(timeout=PUBSUB_POLL_TIMEOUT)
            if message and message.get("type") == "message":
                event = json.loads(message["data"])
                if event.get("type") == "log":
                    # skip entries already sent during replay
                    if event.get("seq", 0) >= next_seq:
                        next_seq = event["seq"] + 1
                        yield _sse("log", {key: event[key] for key in ("seq", "timestamp", "level", "message") if key in event}, event_id=event.get("seq"))
                elif event.get("type") == "status":
                    if event.get("status") in TERMINAL_STATUSES:
                        events, next_seq = _drain_log(analysis_id, next_seq)
                        yield from events
                        yield _sse("status", event)
                        return
                    yield _sse("status", event)

            now = time.monotonic()
            if now - last_keepalive >= KEEPALIVE_INTERVAL:
                yield ": keepalive\n\n"
                last_keepalive = now
            if now - last_state_check >= STATE_CHECK_INTERVAL:
                # Redis state is the source of truth: catch terminal states whose pub/sub event was missed.
                state = get_analysis(analysis_id)
                if state["status"] in TERMINAL_STATUSES:
                    events, next_seq = _drain_log(analysis_id, next_seq)
                    yield from events
                    yield _sse("status", _status_event(state))
                    return
                last_state_check = now
    except (redis.RedisError, AnalysisStorageError, AnalysisNotFoundError) as exc:
        # End the stream cleanly on storage problems; the client can reconnect.
        log.warning("Event stream for analysis %s ended (%s)", analysis_id, type(exc).__name__)
    finally:
        try:
            pubsub.close()
        except redis.RedisError as exc:
            log.debug("Failed to close pub/sub for analysis %s (%s)", analysis_id, type(exc).__name__)
