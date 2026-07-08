import json

import flask
import markupsafe

from app.services import case_from_email, list_emails, run_analysis
from app.utils.ws_logger import WebSocketLogger

bp = flask.Blueprint("api", __name__, url_prefix="/api")

socketio = None

def init_routes(socketio_instance):
	global socketio
	socketio = socketio_instance

@bp.route('/list', methods = ['GET'])
def obtain_emails_to_analyze():
	# Obtain the list of emails
	emails_info = list_emails.main()
	if emails_info is None:
		return flask.make_response(json.dumps({'success': False}), 500)

	# Format and return
	response = flask.jsonify(emails_info)
	return response

# Analyze the email and obtain the verdict
@bp.route('/analysis', methods = ['POST'])
def analyze_email():
	# UID of the email to analyze and sid of the client obtained from the request
	mail_uid = markupsafe.escape(flask.request.form.get("mailUID"))
	sid_client = markupsafe.escape(flask.request.form.get("sid"))

	# Instantiate the object used for logging by the other modules
	wsl = WebSocketLogger(socketio, sid_client)

	# Call the modules used to create the case and run the analysis
	new_case_id, external_from_field = case_from_email.main(wsl, mail_uid)
	if new_case_id is None or external_from_field is None:
		return flask.make_response(json.dumps({'success': False}), 500)

	verdict = run_analysis.main(wsl, new_case_id, external_from_field)
	if verdict is None:
		return flask.make_response(json.dumps({'success': False}), 500)

	# Format response and return
	response = flask.jsonify(verdict)
	return response
