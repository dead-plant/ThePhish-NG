from typing import Optional

_analyzer_configs: Optional[dict] = None

def initialize(analyzer_levels: dict):
	global _analyzer_configs

	if not isinstance(analyzer_levels, dict):
		raise ValueError("expected a JSON object at the top level")

	for analyzer_name, analyzer_conf in analyzer_levels.items():
		if not isinstance(analyzer_conf, dict):
			raise ValueError("entry '{}' must be a JSON object".format(analyzer_name))
		if not isinstance(analyzer_conf.get('dataType'), list):
			raise ValueError("entry '{}.dataType' must be a list".format(analyzer_name))
		if not isinstance(analyzer_conf.get('levelMapping'), dict):
			raise ValueError("entry '{}.levelMapping' must be a JSON object".format(analyzer_name))

	_analyzer_configs = analyzer_levels

def get() -> dict:
	if _analyzer_configs is None:
		raise RuntimeError("Analyzer levels have not been initialized")

	return _analyzer_configs

def map_level(analyzer_name: str, observable_type: str, level: str) -> str:
	analyzer_conf = get().get(analyzer_name)
	if analyzer_conf is None:
		return level

	if observable_type not in analyzer_conf.get('dataType', []):
		return level

	return analyzer_conf.get('levelMapping', {}).get(level, level)
