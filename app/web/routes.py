from flask import render_template

from app import config
from app.web import web_bp


def _webapp_context() -> dict[str, str | None]:
    """Return configured external-service links used by web templates."""
    webapp = config.get_app_config()["webapp"]
    return {
        "webapp_thehive_url": webapp.get("thehive_url"),
        "webapp_cortex_url": webapp.get("cortex_url"),
        "webapp_misp_url": webapp.get("misp_url"),
    }


@web_bp.route("/")
def index():
    """Render the email-listing page."""
    return render_template("index.html", **_webapp_context())


@web_bp.route("/analysis/<analysis_id>")
def analysis_page(analysis_id: str):
    """Render a persistent analysis view; the browser loads API state."""
    return render_template(
        "analysis.html",
        analysis_id=analysis_id,
        **_webapp_context(),
    )
