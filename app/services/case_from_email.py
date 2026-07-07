import io
import base64
import hashlib
import email
import email.header, email.utils, email.parser, email.generator
import json
import logging
from typing import Optional, Any
import emoji
import urllib.parse
import traceback
import ioc_finder
from thehive4py import TheHiveApi
from thehive4py.types.case import OutputCase

import utils.log
import utils.whitelist
import utils.imap
from utils.ws_logger import WebSocketLogger

import tempfile
import os

def _save_tuple_to_tempfile(file_tuple):
	"""Accepts (BytesIO, filename) and writes to a NamedTemporaryFile, returns its path"""
	bio, fname = file_tuple
	bio.seek(0)
	fd, path = tempfile.mkstemp(prefix="thephish_", suffix="_" + os.path.basename(fname))
	with os.fdopen(fd, 'wb') as f:
		f.write(bio.read())
	return path


# Global variable used for logging
log: logging.Logger


# Use the ioc-finder module to extract observables from a string buffer and add to the list only if they are not whitelisted
def search_observables(buffer, whitelist: dict, wsl: WebSocketLogger):
	observables = []
	iocs = {}
	iocs['email_addresses'] = ioc_finder.parse_email_addresses(buffer)
	iocs['ipv4s'] = ioc_finder.parse_ipv4_addresses(buffer)
	iocs['domains'] = ioc_finder.parse_domain_names(buffer)
	# Option to parse URLs without a scheme (e.g. without https://)
	iocs['urls'] = ioc_finder.parse_urls(buffer, parse_urls_without_scheme=False)
	for mail in iocs['email_addresses']:
		if utils.whitelist.is_whitelisted(whitelist, 'mail', mail):
			log.info("Skipped whitelisted observable mail: {0}".format(mail))
			wsl.emit_info("Skipped whitelisted observable mail: {0}".format(mail))
		else:
			log.info("Found observable mail: {0}".format(mail))
			wsl.emit_info("Found observable mail: {0}".format(mail))
			observables.append({'type': 'mail', 'value': mail})
	for ip in iocs['ipv4s']:
		if utils.whitelist.is_whitelisted(whitelist, 'ip', ip):
			log.info("Skipped whitelisted observable ip: {0}".format(ip))
			wsl.emit_info("Skipped whitelisted observable ip: {0}".format(ip))
		else:
			log.info("Found observable ip: {0}".format(ip))
			wsl.emit_info("Found observable ip: {0}".format(ip))
			observables.append({'type': 'ip', 'value': ip})
	for domain in iocs['domains']:
		if utils.whitelist.is_whitelisted(whitelist, 'domain', domain):
			log.info("Skipped whitelisted observable domain: {0}".format(domain))
			wsl.emit_info("Skipped whitelisted observable domain: {0}".format(domain))
		else:
			log.info("Found observable domain: {0}".format(domain))
			wsl.emit_info("Found observable domain: {0}".format(domain))
			observables.append({'type': 'domain', 'value': domain})
	for url in iocs['urls']:
		if utils.whitelist.is_whitelisted(whitelist, 'url', url):
			log.info("Skipped whitelisted observable url: {0}".format(url))
			wsl.emit_info("Skipped whitelisted observable url: {0}".format(url))
		else:
			log.info("Found observable url: {0}".format(url))
			wsl.emit_info("Found observable url: {0}".format(url))
			observables.append({'type': 'url', 'value': url})
	return observables


# Use the mail UID of the selected email to fetch only that email from the mailbox
def obtain_eml(connection, mail_uid, config: dict, wsl: WebSocketLogger):
	# Read all the unseen emails from this folder
	connection.select(config['imap']['folder'])
	typ, dat = connection.search(None, '(UNSEEN)')

	# The dat[0] variable contains the IDs of all the unread emails
	# The IDs are obtained by using the split function and the length of the array is the number of unread emails
	# If the selected mail uid is present in the list, then process only that email
	if mail_uid.encode() in dat[0].split():
		typ, dat = connection.fetch(mail_uid.encode(), '(RFC822)')
		if typ != 'OK':
			log.error(dat[-1])
			wsl.emit_error(dat[-1])
		message = dat[0][1]
		# The fetch operation flags the message as seen by default
		log.info("Message {0} flagged as read".format(mail_uid))
		wsl.emit_info("Message {0} flagged as read".format(mail_uid))

		# Obtain the From field of the external email that will be used to send the verdict to the user
		msg = email.message_from_bytes(message)
		decode = email.header.decode_header(msg['From'])[0]
		if decode[1] is not None:
			external_from_field = decode[0].decode(decode[1])
		else:
			external_from_field = str(decode[0])
		parsed_from_field = email.utils.parseaddr(external_from_field)
		if len(parsed_from_field) > 1:
			external_from_field = parsed_from_field[1]

		# Variable used to detect the mimetype of the email parts
		mimetype = None

		# Variable that will contain the internal EML file
		internal_msg = None

		# Walk the multipart structure of the email (now only the EML part is needed)
		for part in msg.walk():
			mimetype = part.get_content_type()
			# If the content type of this part is the rfc822 message, then stop because the EML attachment is the last part
			# If there is any other part after the rfc822 part, then it may be related to the internal email, so it must not be considered
			# Both message/rfc822 and application/octet-stream types are considered due to differences in how the attachment is handled by different mail clients
			if mimetype in ['application/octet-stream', 'message/rfc822']:
				# Obtain the internal EML file in both cases
				if mimetype == 'application/octet-stream':
					eml_payload = part.get_payload(decode=True)
					internal_msg = email.message_from_bytes(eml_payload)
				elif mimetype == 'message/rfc822':
					eml_payload = part.get_payload(decode=False)[0]
					try:
						internal_msg = email.message_from_string(base64.b64decode(str(eml_payload)).decode())
					except:
						internal_msg = eml_payload

				# If the EML attachment has been found, then break the for
				break

		return internal_msg, external_from_field

	else:
		# Handle multiple analysts that select the same email from more than one tab
		log.error(
			"The email with UID {} has already been analyzed. Please refresh the page and retry.".format(mail_uid))
		wsl.emit_error(
			"The email with UID {} has already been analyzed. Please refresh the page and retry.".format(mail_uid))
		return None


# Parse the EML file and extract the observables
def parse_eml(internal_msg, whitelist: dict, wsl: WebSocketLogger):
	# Obtain the subject of the internal email
	# This is not straightforward since the subject might be splitted in two or more parts
	decode_subj = email.header.decode_header(internal_msg['Subject'])
	decoded_elements_subj = []
	for decode_elem in decode_subj:
		if decode_elem[1] is not None:
			if str(decode_elem[1]) == 'unknown-8bit':
				decoded_elements_subj.append(decode_elem[0].decode())
			else:
				decoded_elements_subj.append(decode_elem[0].decode(decode_elem[1]))
		else:
			if isinstance(decode_elem[0], str):
				decoded_elements_subj.append(str(decode_elem[0]))
			else:
				decoded_elements_subj.append(decode_elem[0].decode())
		subject_field = ''.join(decoded_elements_subj)

	log.info("Analyzing attached message with subject: {}".format(subject_field))
	wsl.emit_info("Analyzing attached message with subject: {}".format(subject_field))

	# List of attachments of the internal email
	attachments = []

	# List of attachment hashes
	hashes_attachments = []

	# List of observables found in the body of the internal email
	observables_body = []

	# Dictionary containing a list of observables found in each header field
	observables_header = {}

	# List of header fields to consider when searching for observables in the header
	header_fields_list = [
		'To',
		'From',
		'Sender',
		'Cc',
		'Delivered-To',
		'Return-Path',
		'Reply-To',
		'Bounces-to',
		'Received',
		'X-Received',
		'X-OriginatorOrg',
		'X-Sender-IP',
		'X-Originating-IP',
		'X-SenderIP',
		'X-Originating-Email'
	]

	# Extract header fields
	parser = email.parser.HeaderParser()
	header_fields = parser.parsestr(internal_msg.as_string())

	# Search the observables in the values of all the selected header fields
	# Since a field may appear more than one time (e.g. Received:), the lists need to be initialized and then extended
	i = 0
	while i < len(header_fields.keys()):
		if header_fields.keys()[i] in header_fields_list:
			if not observables_header.get(header_fields.keys()[i]):
				observables_header[header_fields.keys()[i]] = []
			observables_header[header_fields.keys()[i]].extend(
				search_observables(header_fields.values()[i], whitelist, wsl))
		i += 1

	# Walk the multipart structure of the internal email
	for part in internal_msg.walk():
		mimetype = part.get_content_type()
		content_disposition = part.get_content_disposition()
		if content_disposition != "attachment":
			# Extract the observables from the body (from both text/plain and text/html parts) using the search_observables function
			if mimetype == "text/plain":
				try:
					body = part.get_payload(decode=True).decode()
				except UnicodeDecodeError:
					body = part.get_payload(decode=True).decode('ISO-8859-1')
				observables_body.extend(search_observables(body, whitelist, wsl))
			elif mimetype == "text/html":
				try:
					html = part.get_payload(decode=True).decode()
				except UnicodeDecodeError:
					html = part.get_payload(decode=True).decode('ISO-8859-1')
				# Handle URL encoding
				html_urldecoded = urllib.parse.unquote(html.replace("&amp;", "&"))
				observables_body.extend(search_observables(html_urldecoded, whitelist, wsl))
		# Extract attachments
		else:
			filename = part.get_filename()
			if filename and mimetype:
				# Add the attachment if it is not whitelisted (in terms of filename or filetype)
				if utils.whitelist.is_whitelisted(whitelist, 'filename', filename) or utils.whitelist.is_whitelisted(
						whitelist, 'filetype', mimetype):
					log.info("Skipped whitelisted observable file: {0}".format(filename))
					wsl.emit_info("Skipped whitelisted observable file: {0}".format(filename))
				else:
					inmem_file = io.BytesIO(part.get_payload(decode=1))
					attachments.append((inmem_file, filename))
					log.info("Found observable file: {0}".format(filename))
					wsl.emit_info("Found observable file: {0}".format(filename))
					# Calculate the hash of the just found attachment
					sha256 = hashlib.sha256()
					sha256.update(part.get_payload(decode=1))
					hash_attachment = {}
					hash_attachment['hashValue'] = sha256.hexdigest()
					hash_attachment['hashedAttachment'] = filename
					if utils.whitelist.is_whitelisted(whitelist, 'hash', hash_attachment['hashValue']):
						log.info("Skipped whitelisted observable hash: {0}".format(hash_attachment['hashValue']))
						wsl.emit_info("Skipped whitelisted observable hash: {0}".format(hash_attachment['hashValue']))
					else:
						hashes_attachments.append(hash_attachment)
						log.info(
							"Found observable hash {0} calculated from file: {1}".format(hash_attachment['hashValue'],
																						 filename))
						wsl.emit_info(
							"Found observable hash {0} calculated from file: {1}".format(hash_attachment['hashValue'],
																						 filename))

	# Create a tuple containing the eml file and the name it should have as an observable
	filename = subject_field + ".eml"
	inmem_file = io.BytesIO()
	gen = email.generator.BytesGenerator(inmem_file)
	gen.flatten(internal_msg)
	eml_file_tuple = (inmem_file, filename)

	# Workaround to prevent HTML tags to appear inside the URLs (splits on < or >)
	for observable_body in observables_body:
		if observable_body['type'] == "url":
			observable_body['value'] = observable_body['value'].replace(">", "<").split("<")[0]

	return subject_field, observables_header, observables_body, attachments, hashes_attachments, eml_file_tuple


# Create the case on TheHive and add the observables to it
def create_case(subject_field, observables_header, observables_body, attachments, hashes_attachments, eml_file_tuple,
				config: dict, api_thehive: TheHiveApi, wsl: WebSocketLogger):
	# Create the case template first if it does not exist
	case_templates = api_thehive.case_template.find(
		filters={"_eq": {"_field": "name", "_value": "ThePhish"}}
	)

	if len(case_templates) == 0:
		# Create tasks for the template
		tasks = [
			{"title": "ThePhish notification"},
			{"title": "ThePhish analysis"},
			{"title": "ThePhish result"}
		]

		case_template = {
			"name": "ThePhish",
			"titlePrefix": "[ThePhish] ",
			"tasks": tasks
		}

		created_template = api_thehive.case_template.create(case_template)
		if created_template:
			log.info('Template ThePhish created successfully')
			wsl.emit_info('Template ThePhish created successfully')
		else:
			log.error('Cannot create template')
			wsl.emit_error('Cannot create template')
			return

	# Create the case on TheHive
	# The emojis are removed to prevent problems when exporting the case to MISP
	case_data = {
		"title": str(emoji.replace_emoji(subject_field)),
		"tlp": int(config['case']['tlp']),
		"pap": int(config['case']['pap']),
		"flag": False,
		"tags": config['case']['tags'],
		"description": "Case created automatically by ThePhish",
		"caseTemplate": "ThePhish",
	}

	new_case = api_thehive.case.create(case_data)
	if new_case:
		new_id = new_case["_id"]
		new_case_id = new_case["number"]
		log.info('Created case {}'.format(new_case_id))
		wsl.emit_info('Created case {}'.format(new_case_id))

		# Add observables found in the mail header
		for header_field in observables_header:
			for observable_header in observables_header[header_field]:
				observable = {
					"dataType": observable_header['type'],
					"data": observable_header['value'],
					"ioc": False,
					"tags": ['email', 'email_header', 'email_header_{}'.format(header_field)],
					"message": 'Found in the {} field of the email header'.format(header_field)
				}
				created_obs = api_thehive.case.create_observable(case_id=new_id, observable=observable)
				if created_obs:
					log.info('Added observable {0}: {1} to case {2}'.format(observable_header['type'],
																			observable_header['value'], new_case_id))
					wsl.emit_info('Added observable {0}: {1} to case {2}'.format(observable_header['type'],
																				 observable_header['value'],
																				 new_case_id))
				else:
					log.debug(
						'Cannot add observable {0}: {1}'.format(observable_header['type'], observable_header['value']))

		# Add observables found in the mail body
		for observable_body in observables_body:
			observable = {
				"dataType": observable_body['type'],
				"data": observable_body['value'],
				"ioc": False,
				"tags": ['email', 'email_body'],
				"message": 'Found in the email body'
			}
			created_obs = api_thehive.case.create_observable(case_id=new_id, observable=observable)
			if created_obs:
				log.info(
					'Added observable {0}: {1} to case {2}'.format(observable_body['type'], observable_body['value'],
																   new_case_id))
				wsl.emit_info(
					'Added observable {0}: {1} to case {2}'.format(observable_body['type'], observable_body['value'],
																   new_case_id))
			else:
				log.debug('Cannot add observable {0}: {1}'.format(observable_body['type'], observable_body['value']))

		# Add attachments
		for attachment in attachments:
			# For file observables in v2, we need to use the create_file method
			tmp_path = _save_tuple_to_tempfile(attachment)
			created_obs = api_thehive.case.create_observable(
				case_id=new_id,
				observable={'dataType': 'file', 'ioc': False, 'tags': ['email','email_attachment'], 'message': 'Found as email attachment'},
				observable_path=tmp_path
			)
			if created_obs:
				log.info('Added observable file {0} to case {1}'.format(attachment[1], new_case_id))
				wsl.emit_info('Added observable file {0} to case {1}'.format(attachment[1], new_case_id))
			else:
				log.debug('Cannot add observable: file {0}'.format(attachment[1]))

		# Add hashes of the attachments
		for hash_attachment in hashes_attachments:
			observable = {
				"dataType": 'hash',
				"data": hash_attachment['hashValue'],
				"ioc": False,
				"tags": ['email', 'email_attachment_hash'],
				"message": 'Hash of attachment "{}"'.format(hash_attachment['hashedAttachment'])
			}
			created_obs = api_thehive.case.create_observable(case_id=new_id, observable=observable)
			if created_obs:
				log.info('Added observable hash: {0} to case {1}'.format(hash_attachment['hashValue'], new_case_id))
				wsl.emit_info(
					'Added observable hash: {0} to case {1}'.format(hash_attachment['hashValue'], new_case_id))
			else:
				log.debug('Cannot add observable hash: {0}'.format(hash_attachment['hashValue']))

		# Add eml file (using the tuple)
		if eml_file_tuple:
			tmp_eml_path = _save_tuple_to_tempfile(eml_file_tuple)
			created_obs = api_thehive.case.create_observable(
				case_id=new_id,
				observable={'dataType': 'file', 'ioc': False, 'tags': ['email','email_sample'], 'message': 'Attached email in eml format'},
				observable_path=tmp_eml_path
			)
			if created_obs:
				log.info('Added observable file {0} to case {1}'.format(eml_file_tuple[1], new_case_id))
				wsl.emit_info('Added observable file {0} to case {1}'.format(eml_file_tuple[1], new_case_id))
			else:
				log.debug('Cannot add observable: file {0}'.format(eml_file_tuple[1]))

	else:
		log.error('Cannot create case')
		wsl.emit_error('Cannot create case')
		return

	# Return the id of the just created case on which to run the analysis
	return new_case


# Main function called from outside
# The wsl is not a global variable to support multiple tabs
def main(config: dict, wsl: WebSocketLogger, mail_uid) -> Optional[tuple[Any | None, Any]]:
	# Create Logger
	global log
	log = utils.log.get_logger("case_from_email")
	if log is None:
		return None

	# Connect to IMAP server
	try:
		connection = utils.imap.connect(config, log, wsl)
	except Exception as e:
		log.error("Error while trying to connect to IMAP server: {}".format(traceback.format_exc()))
		wsl.emit_error("Error while trying to connect to IMAP server")
		return None

	# Call the obtain_eml function
	try:
		internal_msg, external_from_field = obtain_eml(connection, mail_uid, config, wsl)
	except Exception as e:
		log.error("Error while trying to obtain the internal eml file: {}".format(traceback.format_exc()))
		wsl.emit_error("Error while trying to obtain the internal eml file")
		return None

	# Load whitelist
	whitelist = utils.whitelist.load(log, wsl)
	if whitelist is None:
		return None

	# Call the parse_eml function
	try:
		subject_field, observables_header, observables_body, attachments, hashes_attachments, eml_file_tuple = parse_eml(
			internal_msg, whitelist, wsl)
	except Exception as e:
		log.error("Error while trying to parse the internal eml file: {}".format(traceback.format_exc()))
		wsl.emit_error("Error while trying to parse the internal eml file")
		return None

	# Create thehive api
	try:
		insecure = config['thehive']['tlsinsecure']
		if insecure == "no":
			verifycert = True
		elif insecure == "yes":
			verifycert = False
		else:
			raise Exception("insecure must be 'yes' or 'no'")

		# Object needed to use TheHive4py v2
		api_thehive = TheHiveApi(
			url=config['thehive']['url'],
			apikey=config['thehive']['apikey'],
			verify=verifycert
		)

	except Exception as e:
		log.error("Error while trying to create thehive api: {}".format(traceback.format_exc()))
		wsl.emit_error("Error while trying to create thehive api")
		return None

	# Call the create_case function
	try:
		new_case = create_case(subject_field, observables_header, observables_body, attachments, hashes_attachments,
							   eml_file_tuple, config, api_thehive, wsl)
	except Exception as e:
		log.error("Error while trying to create the case: {}".format(traceback.format_exc()))
		wsl.emit_error("Error while trying to create the case")
		return None

	return new_case, external_from_field
