from flask import render_template

from app.web import web_bp
from app import config

# The main page
@web_bp.route("/")
def index():
    webapp = config.get_app_config()["webapp"]
    thehive_url = webapp.get("thehive_url")
    cortex_url = webapp.get("cortex_url")
    misp_url = webapp.get("misp_url")

    return render_template("index.html", webapp_thehive_url=thehive_url, webapp_cortex_url=cortex_url, webapp_misp_url=misp_url)
