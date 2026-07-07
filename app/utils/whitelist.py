import json
import logging
from pathlib import Path
import re
import traceback
from typing import Optional
from utils.ws_logger import WebSocketLogger

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load(log: logging.Logger, wsl: Optional[WebSocketLogger] = None) -> Optional[dict]:
	# Read the whitelist file, which is composed by various parts:
		# - The exact matching part
		# - The regex matching part
		# - Three lists of domains that are used to whitelist subdomains, URLs and email addresses that contain them

	whitelist = {}
	try:
		with open(CONFIG_DIR / 'whitelist.json') as whitelist_file:
			whitelist_dict = json.load(whitelist_file)
			whitelist['mailExact'] = whitelist_dict['exactMatching']['mail']
			whitelist['mailRegex'] = whitelist_dict['regexMatching']['mail']
			whitelist['ipExact'] = whitelist_dict['exactMatching']['ip']
			whitelist['ipRegex'] = whitelist_dict['regexMatching']['ip']
			whitelist['domainExact'] = whitelist_dict['exactMatching']['domain']
			whitelist['domainRegex'] = whitelist_dict['regexMatching']['domain']
			whitelist['urlExact'] = whitelist_dict['exactMatching']['url']
			whitelist['urlRegex'] = whitelist_dict['regexMatching']['url']
			whitelist['filenameExact'] = whitelist_dict['exactMatching']['filename']
			whitelist['filenameRegex'] = whitelist_dict['regexMatching']['filename']
			whitelist['filetypeExact'] = whitelist_dict['exactMatching']['filetype']
			whitelist['hashExact'] = whitelist_dict['exactMatching']['hash']

			# The domains in the last three lists are used to create three lists of regular expressions that serve to whitelist subdomains, URLs and email addresses based on those domains
			whitelist['regexDomainsInSubdomains'] = [r'^(.+\.|){0}$'.format(domain.replace(r'.', r'\.')) for domain in whitelist_dict['domainsInSubdomains']]
			whitelist['regexDomainsInURLs'] = [r'^(http|https):\/\/([^\/]+\.|){0}(\/.*|\?.*|\#.*|)$'.format(domain.replace(r'.', r'\.')) for domain in whitelist_dict['domainsInURLs']]
			whitelist['regexDomainsInEmails'] = [r'^.+@(.+\.|){0}$'.format(domain.replace(r'.', r'\.')) for domain in whitelist_dict['domainsInEmails']]

	except Exception as e:
		log.error("Error while trying to open the file 'config/whitelist.json': {}".format(traceback.format_exc()))
		if wsl is not None:
			wsl.emit_error("Error while trying to open the file 'config/whitelist.json'")
		return None

	return whitelist


def is_whitelisted(whitelist: dict, obs_type: str, obs_value) -> bool:
	# Check if an observable is whitelisted with an exact match or with a regex match

	obs_value = obs_value.lower()

	found = False
	if (not found) and (obs_value in whitelist[obs_type + 'Exact']):
		found = True
	if (not found) and (obs_type == 'domain'):
		for regex in whitelist['regexDomainsInSubdomains']:
			if re.search(regex, obs_value):
				found = True
	if (not found) and (obs_type == 'url'):
		for regex in whitelist['regexDomainsInURLs']:
			if re.search(regex, obs_value):
				found = True
	if (not found) and (obs_type == 'mail'):
		for regex in whitelist['regexDomainsInEmails']:
			if re.search(regex, obs_value):
				found = True
	if (not found) and (obs_type not in ['hash', 'filetype']):
		for regex in whitelist[obs_type+'Regex']:
			if re.search(regex, obs_value):
				found = True
	return found
