from gevent import monkey
monkey.patch_all()

import json
import logging
from pathlib import Path
import flask
import flask_socketio
from api import routes as api_routes
from web import routes as web_routes
import utils.analyzer_levels
import utils.config
import utils.log
import utils.whitelist

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = APP_DIR.parent / "config"
log = logging.getLogger(Path(__file__).stem)
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
		_initialize_from_json("logging_conf.json", utils.log.initialize)
		_initialize_from_json("configuration.json", utils.config.initialize)
		_initialize_from_json("whitelist.json", utils.whitelist.initialize)
		_initialize_from_json("analyzers_level_conf.json", utils.analyzer_levels.initialize)
	except RuntimeError as e:
		print("[ERROR]_[thephish_app]: {}".format(e))
		return 1

	web_routes.init_routes()
	api_routes.init_routes(socketio)

	socketio.run(app, host='0.0.0.0', port=8080)
	return 0

if __name__ == "__main__":
	raise SystemExit(main())
