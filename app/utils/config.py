import logging
from typing import Optional

log = logging.getLogger(__name__)

_config: Optional[dict] = None

def initialize(config: dict):
	global _config

	if not isinstance(config, dict):
		log.error("Configuration initialization failed: expected top-level JSON object, got %s", type(config).__name__)
		raise ValueError("expected a JSON object at the top level")

	_config = config
	log.info("Configuration initialized with sections: %s", ", ".join(sorted(config.keys())) or "<none>")


def get() -> dict:
	if _config is None:
		log.error("Configuration requested before initialization")
		raise RuntimeError("Configuration has not been initialized")

	log.debug("Configuration requested")
	return _config
