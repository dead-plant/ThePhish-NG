import logging

from flask import Response, jsonify, request

from app.api import api_bp
from app.services import analysis, listing

log = logging.getLogger(__name__)


@api_bp.errorhandler(listing.ImapConnectionError)
def handle_imap_connection_error(error):
    log.error("Failed to list emails because the IMAP connection failed", exc_info=(type(error), error, error.__traceback__))
    return jsonify(
        success=False,
        error={
            "code": "imap_connection_failed",
            "message": "An IMAP connection error occurred while trying to list emails. Please try again later.",
        },
    ), 503


@api_bp.errorhandler(listing.ListEmailsError)
def handle_list_emails_error(error):
    log.error("Failed to list emails", exc_info=(type(error), error, error.__traceback__))
    return jsonify(
        success=False,
        error={
            "code": "internal_server_error",
            "message": "An internal server error occurred while listing emails. Please try again later.",
        },
    ), 500


# Simple health endpoint
@api_bp.route("/health")
def health():
    return jsonify(status="ok")


@api_bp.route("/emails", methods=["GET"])
def list_emails():
    return jsonify(listing.list_emails())


@api_bp.errorhandler(analysis.InvalidMailUidError)
def handle_invalid_mail_uid_error(error):
    log.debug("Rejected analysis request: %s", error)
    return jsonify(
        success=False,
        error={
            "code": "invalid_mail_uid",
            "message": str(error),
        },
    ), 400


@api_bp.errorhandler(analysis.AnalysisNotFoundError)
def handle_analysis_not_found_error(error):
    log.debug("Analysis not found: %s", error)
    return jsonify(
        success=False,
        error={
            "code": "analysis_not_found",
            "message": "The requested analysis does not exist or has expired.",
        },
    ), 404


@api_bp.errorhandler(analysis.AnalysisQueueError)
def handle_analysis_queue_error(error):
    log.error("Failed to queue an analysis", exc_info=(type(error), error, error.__traceback__))
    return jsonify(
        success=False,
        error={
            "code": "analysis_backend_unavailable",
            "message": "The analysis could not be queued. Please try again later.",
        },
    ), 503


@api_bp.errorhandler(analysis.AnalysisStorageError)
def handle_analysis_storage_error(error):
    log.error("Analysis state storage failed", exc_info=(type(error), error, error.__traceback__))
    return jsonify(
        success=False,
        error={
            "code": "analysis_storage_unavailable",
            "message": "The analysis state storage is unavailable. Please try again later.",
        },
    ), 503


@api_bp.errorhandler(analysis.AnalysisError)
def handle_analysis_error(error):
    log.error("Analysis request failed", exc_info=(type(error), error, error.__traceback__))
    return jsonify(
        success=False,
        error={
            "code": "internal_server_error",
            "message": "An internal server error occurred. Please try again later.",
        },
    ), 500


@api_bp.route("/analyses", methods=["POST"])
def create_analysis():
    payload = request.get_json(silent=True)
    mail_uid = payload.get("mail_uid") if isinstance(payload, dict) else None
    state = analysis.start_analysis(mail_uid)
    return jsonify(state), 202


@api_bp.route("/analyses/<analysis_id>", methods=["GET"])
def get_analysis(analysis_id):
    return jsonify(analysis.get_analysis(analysis_id))


@api_bp.route("/analyses/<analysis_id>/log", methods=["GET"])
def get_analysis_log(analysis_id):
    return jsonify(analysis.get_analysis_log(analysis_id))


@api_bp.route("/analyses/<analysis_id>/stream", methods=["GET"])
def stream_analysis(analysis_id):
    # raises AnalysisNotFoundError before streaming starts, so the 404 handler still applies
    stream = analysis.stream_analysis_events(analysis_id)
    return Response(
        stream,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
