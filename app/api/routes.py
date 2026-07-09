from flask import jsonify

from app.api import api_bp
from app.extensions import socketio

# Simple health endpoint
@api_bp.route("/health")
def health():
    return jsonify(status="ok")
