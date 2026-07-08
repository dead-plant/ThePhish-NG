import logging

import flask
from app.utils import config as config_utils

log = logging.getLogger(__name__)

bp = flask.Blueprint("web", __name__, template_folder="templates", static_folder="static")

def init_routes():
	pass

# The main page
@bp.route("/")
def homepage():
	config = config_utils.get()
	thehive = config['web']['navbar']['thehive']
	cortex = config['web']['navbar']['cortex']
	misp = config['web']['navbar']['misp']

	return flask.render_template("index.html", conf_web_navbar_thehive=thehive, conf_web_navbar_cortex=cortex, conf_web_navbar_misp=misp)
