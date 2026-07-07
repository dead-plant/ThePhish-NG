import json
import logging
import logging.config
from pathlib import Path
import traceback
from typing import Optional

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def get_logger(name: str) -> Optional[logging.Logger]:
	# Logging configuration
	try:
		with open(CONFIG_DIR / 'logging_conf.json') as log_conf:
			log_conf_dict = json.load(log_conf)
			logging.config.dictConfig(log_conf_dict)
	except Exception as e:
		print("[ERROR]_[list_emails]: Error while trying to open the file 'config/logging_conf.json'. It cannot be read or it is not valid: {}".format(traceback.format_exc()))
		return None

	return logging.getLogger(name)
