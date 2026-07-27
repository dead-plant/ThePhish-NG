"""Narrow event-sink interface for the analysis workflow stages.

Stages report their progress through this protocol instead of a concrete
logger, so the same stage code runs against the Redis-backed AnalysisLogger
in production and a simple recording sink in tests.
"""

from typing import Protocol


class EventSink(Protocol):
    """Operational progress reporting available to a workflow stage."""

    def info(self, message: str) -> None:
        ...

    def warning(self, message: str) -> None:
        ...

    def error(self, message: str) -> None:
        ...
