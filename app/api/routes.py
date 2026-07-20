import logging

from flask import jsonify

from app.api import api_bp
from app.services import listing

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


@api_bp.route("/list", methods=["GET"])
@api_bp.route("/list/emails", methods=["GET"])
def list_emails():
    return jsonify(listing.list_emails())
