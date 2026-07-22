"""Shared exceptions of the analysis service."""


class AnalysisError(RuntimeError):
    """Raised when an analysis cannot be started or fails fatally."""


class InvalidMailUidError(AnalysisError):
    """Raised when the submitted mail UID is not a positive integer."""


class AnalysisNotFoundError(AnalysisError):
    """Raised when an analysis does not exist or has expired."""


class AnalysisStorageError(AnalysisError):
    """Raised when the analysis state cannot be read from or written to Redis."""


class AnalysisQueueError(AnalysisError):
    """Raised when the analysis task cannot be queued to the Celery broker."""
