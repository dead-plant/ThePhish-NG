import logging
import logging.config

def initialize(log_conf_dict: dict):
	# Logging configuration
	try:
		logging.config.dictConfig(log_conf_dict)
	except Exception as e:
		_initialized = False
		raise ValueError("invalid logging configuration: {}".format(e)) from e
