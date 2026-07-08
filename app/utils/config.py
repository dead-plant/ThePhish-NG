import logging
from typing import Optional

log = logging.getLogger(__name__)

_config: Optional[dict] = None

def initialize(config: dict):
	global _config

	if not isinstance(config, dict):
		raise ValueError("expected a JSON object at the top level")

	_config = config


def get() -> dict:
	if _config is None:
		raise RuntimeError("Configuration has not been initialized")

	return _config
