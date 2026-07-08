import logging
from typing import Optional

log = logging.getLogger(__name__)

_analyzer_configs: Optional[dict] = None

def initialize(analyzer_levels: dict):
	global _analyzer_configs

	if not isinstance(analyzer_levels, dict):
		log.error("Analyzer level initialization failed: expected top-level JSON object, got %s", type(analyzer_levels).__name__)
		raise ValueError("expected a JSON object at the top level")

	for analyzer_name, analyzer_conf in analyzer_levels.items():
		if not isinstance(analyzer_conf, dict):
			log.error("Invalid analyzer level entry '%s': expected JSON object, got %s", analyzer_name, type(analyzer_conf).__name__)
			raise ValueError("entry '{}' must be a JSON object".format(analyzer_name))
		if not isinstance(analyzer_conf.get('dataType'), list):
			log.error("Invalid analyzer level entry '%s.dataType': expected list", analyzer_name)
			raise ValueError("entry '{}.dataType' must be a list".format(analyzer_name))
		if not isinstance(analyzer_conf.get('levelMapping'), dict):
			log.error("Invalid analyzer level entry '%s.levelMapping': expected JSON object", analyzer_name)
			raise ValueError("entry '{}.levelMapping' must be a JSON object".format(analyzer_name))
		log.debug(
			"Validated analyzer level config for %s: data_types=%s, mapped_levels=%s",
			analyzer_name,
			analyzer_conf.get('dataType', []),
			sorted(analyzer_conf.get('levelMapping', {}).keys()),
		)

	_analyzer_configs = analyzer_levels
	log.info("Analyzer level configuration initialized for %d analyzers", len(analyzer_levels))

def get() -> dict:
	if _analyzer_configs is None:
		log.error("Analyzer level configuration requested before initialization")
		raise RuntimeError("Analyzer levels have not been initialized")

	log.debug("Analyzer level configuration requested")
	return _analyzer_configs

def map_level(analyzer_name: str, observable_type: str, level: str) -> str:
	analyzer_conf = get().get(analyzer_name)
	if analyzer_conf is None:
		log.debug("No level mapping configured for analyzer '%s'; keeping level '%s'", analyzer_name, level)
		return level

	if observable_type not in analyzer_conf.get('dataType', []):
		log.debug(
			"Analyzer '%s' has no level mapping for observable type '%s'; keeping level '%s'",
			analyzer_name,
			observable_type,
			level,
		)
		return level

	mapped_level = analyzer_conf.get('levelMapping', {}).get(level, level)
	if mapped_level == level:
		log.debug("Analyzer '%s' level '%s' unchanged for observable type '%s'", analyzer_name, level, observable_type)
	else:
		log.debug(
			"Mapped analyzer '%s' level for observable type '%s': %s -> %s",
			analyzer_name,
			observable_type,
			level,
			mapped_level,
		)
	return mapped_level
