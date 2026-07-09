from flask import Blueprint

web_bp = Blueprint("web", __name__, template_folder="templates", static_folder="static", static_url_path="/static")

from app.web import routes
