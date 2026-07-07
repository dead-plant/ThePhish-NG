import json
import logging
from pathlib import Path
import sys
import traceback

from gevent import monkey
monkey.patch_all()

import flask
import flask_socketio

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = APP_DIR.parent / "config"
if str(APP_DIR) not in sys.path:
	sys.path.insert(0, str(APP_DIR))

from api import routes as api_routes
from web import routes as web_routes
import utils.log

app = flask.Flask(__name__, template_folder='web/templates', static_folder='web/static')
socketio = flask_socketio.SocketIO(app)
app.register_blueprint(web_routes.bp)
app.register_blueprint(api_routes.bp)

# Create global variables log and config
log: logging.Logger
config: dict

def main():
	global log, config

	# get logger for main
	log = utils.log.get_logger("thephish_app")
	if log is None:
		return 1

	# load config
	try:
		with open(CONFIG_DIR / 'configuration.json') as conf_file:
			config = json.load(conf_file)
	except Exception as e:
		log.error("Error while trying to open the file 'config/configuration.json': {}".format(traceback.format_exc()))
		return 1

	web_routes.init_routes(config)
	api_routes.init_routes(config, socketio)

	# run application
	socketio.run(app, host='0.0.0.0', port=8080)
	return 0


# If eventlet or gevent are installed, their wsgi server will be used
# else Werkzeug will be used
if __name__ == "__main__":
	raise SystemExit(main())
