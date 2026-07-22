"""Analysis service: run the automated phishing analysis of a reported email.

Public interface used by the API routes; the internals live in the package
modules (tracking, pipeline, case_builder, analyzers, notifications).
"""

from app.services.analysis.errors import (
    AnalysisError,
    AnalysisNotFoundError,
    AnalysisQueueError,
    AnalysisStorageError,
    InvalidMailUidError,
)
from app.services.analysis.tracking import get_analysis, get_analysis_log, stream_analysis_events
# Importing the pipeline also registers the Celery task app.services.analysis.run_analysis.
from app.services.analysis.pipeline import start_analysis

__all__ = [
    "AnalysisError",
    "AnalysisNotFoundError",
    "AnalysisQueueError",
    "AnalysisStorageError",
    "InvalidMailUidError",
    "start_analysis",
    "get_analysis",
    "get_analysis_log",
    "stream_analysis_events",
]
