import json
import logging
import os
from pathlib import Path
import sys
import traceback

from gevent import monkey
monkey.patch_all()

import flask
import flask_socketio

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
	sys.path.insert(0, str(APP_DIR))

from utils.ws_logger import WebSocketLogger
import list_emails
import case_from_email
import run_analysis
import markupsafe
import utils.log

app = flask.Flask(__name__, template_folder='web/templates', static_folder='web/static')
socketio = flask_socketio.SocketIO(app)

# Create global variables log and config
log: logging.Logger
config: dict

# The main page
@app.route("/")
def homepage():
	return flask.render_template("index.html")

@app.route('/list', methods = ['GET'])
def obtain_emails_to_analyze():
	# Obtain the list of emails
	emails_info = list_emails.main(config)
	if emails_info is None:
		return flask.make_response(json.dumps({'success': False}), 500)

	# Format and return
	response = flask.jsonify(emails_info)
	return response

# Analyze the email and obtain the verdict
@app.route('/analysis', methods = ['POST'])
def analyze_email():
	# UID of the email to analyze and sid of the client obtained from the request
	mail_uid = markupsafe.escape(flask.request.form.get("mailUID"))
	sid_client = markupsafe.escape(flask.request.form.get("sid"))

	# Instantiate the object used for logging by the other modules
	wsl = WebSocketLogger(socketio, sid_client)

	# Call the modules used to create the case and run the analysis
	new_case_id, external_from_field = case_from_email.main(config, wsl, mail_uid)
	if new_case_id is None or external_from_field is None:
		return flask.make_response(json.dumps({'success': False}), 500)

	verdict = run_analysis.main(config, wsl, new_case_id, external_from_field)
	if verdict is None:
		return flask.make_response(json.dumps({'success': False}), 500)

	# Format response and return
	response = flask.jsonify(verdict)
	return response

def main():
	global log, config

	os.chdir(APP_DIR)

	# get logger for main
	log = utils.log.get_logger("thephish_app")
	if log is None:
		return 1

	# load config
	try:
		with open('conf/configuration.json') as conf_file:
			config = json.load(conf_file)
	except Exception as e:
		log.error("Error while trying to open the file 'conf/configuration.json': {}".format(traceback.format_exc()))
		return 1

	# run application
	socketio.run(app, host='0.0.0.0', port=8080)
	return 0


# If eventlet or gevent are installed, their wsgi server will be used
# else Werkzeug will be used
if __name__ == "__main__":
	raise SystemExit(main())

