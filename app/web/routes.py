import flask

bp = flask.Blueprint("web", __name__)

config = None

def init_routes(app_config):
	global config

	config = app_config

# The main page
@bp.route("/")
def homepage():
	thehive = config['web']['navbar']['thehive']
	cortex = config['web']['navbar']['cortex']
	misp = config['web']['navbar']['misp']

	return flask.render_template("index.html", conf_web_navbar_thehive=thehive, conf_web_navbar_cortex=cortex, conf_web_navbar_misp=misp)
