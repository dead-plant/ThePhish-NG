from gevent import monkey
monkey.patch_all()

import json
import logging, logging.config
from pathlib import Path
import flask
import flask_socketio
from app.api import routes as api_routes
from app.web import routes as web_routes
from app.utils import analyzer_levels, config, whitelist

log = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = APP_DIR.parent / "config"

app = flask.Flask(__name__, static_folder=None)
socketio = flask_socketio.SocketIO(app)
app.register_blueprint(web_routes.bp)
app.register_blueprint(api_routes.bp)

def _load_required_json(filename: str) -> dict:
	display_path = "config/{}".format(filename)
	file_path = CONFIG_DIR / filename

	try:
		with open(file_path) as conf_file:
			data = json.load(conf_file)
	except FileNotFoundError as e:
		raise RuntimeError(
			"Missing required config file '{}'. Expected it at '{}'.".format(display_path, file_path)
		) from e
	except json.JSONDecodeError as e:
		raise RuntimeError(
			"Invalid JSON in required config file '{}' at line {}, column {}: {}.".format(
				display_path, e.lineno, e.colno, e.msg
			)
		) from e
	except OSError as e:
		raise RuntimeError(
			"Cannot read required config file '{}'. Path: '{}'. Details: {}.".format(display_path, file_path, e)
		) from e

	if not isinstance(data, dict):
		raise RuntimeError(
			"Invalid required config file '{}': expected a JSON object at the top level.".format(display_path)
		)

	return data

def _initialize_from_json(filename: str, initialize):
	data = _load_required_json(filename)
	try:
		initialize(data)
	except ValueError as e:
		raise RuntimeError(
			"Invalid required config file 'config/{}': {}.".format(filename, e)
		) from e

def main():
	try:
		_initialize_from_json("logging_conf.json", logging.config.dictConfig)
		
		_initialize_from_json("configuration.json", config.initialize)
		_initialize_from_json("whitelist.json", whitelist.initialize)
		_initialize_from_json("analyzers_level_conf.json", analyzer_levels.initialize)
	except RuntimeError as e:
		print("[ERROR]_[thephish_app]: {}".format(e))
		return 1

	web_routes.init_routes()
	api_routes.init_routes(socketio)

	log.info("starting application...")
	socketio.run(app, host='0.0.0.0', port=8080)
	return 0
