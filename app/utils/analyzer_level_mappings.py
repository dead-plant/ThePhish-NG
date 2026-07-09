import logging
from app import config

log = logging.getLogger(__name__)


def _verify_config(analyzer_levels: dict) -> dict:
    if not isinstance(analyzer_levels, dict):
        log.error("Analyzer level initialization failed: expected top-level JSON object, got %s",
                  type(analyzer_levels).__name__)
        raise ValueError("expected a JSON object at the top level")

    for analyzer_name, analyzer_conf in analyzer_levels.items():
        if not isinstance(analyzer_name, str):
            log.error("Invalid analyzer level entry name: expected string, got %s", type(analyzer_name).__name__)
            raise ValueError("analyzer names must be strings")
        if not isinstance(analyzer_conf, dict):
            log.error("Invalid analyzer level entry '%s': expected JSON object, got %s", analyzer_name,
                      type(analyzer_conf).__name__)
            raise ValueError("entry '{}' must be a JSON object".format(analyzer_name))
        if not isinstance(analyzer_conf.get('dataType'), list):
            log.error("Invalid analyzer level entry '%s.dataType': expected list", analyzer_name)
            raise ValueError("entry '{}.dataType' must be a list".format(analyzer_name))
        if not all(isinstance(data_type, str) for data_type in analyzer_conf.get('dataType')):
            log.error("Invalid analyzer level entry '%s.dataType': expected only strings", analyzer_name)
            raise ValueError("entry '{}.dataType' must contain only strings".format(analyzer_name))
        if not isinstance(analyzer_conf.get('levelMapping'), dict):
            log.error("Invalid analyzer level entry '%s.levelMapping': expected JSON object", analyzer_name)
            raise ValueError("entry '{}.levelMapping' must be a JSON object".format(analyzer_name))
        if not all(isinstance(source, str) and isinstance(target, str) for source, target in
                   analyzer_conf.get('levelMapping').items()):
            log.error("Invalid analyzer level entry '%s.levelMapping': expected string keys and values", analyzer_name)
            raise ValueError("entry '{}.levelMapping' must contain only string keys and values".format(analyzer_name))
        log.debug(
            "Validated analyzer level config for %s: data_types=%s, mapped_levels=%s",
            analyzer_name,
            analyzer_conf.get('dataType', []),
            sorted(analyzer_conf.get('levelMapping', {}).keys()),
        )

    log.info("Analyzer level configuration verified for %d analyzers", len(analyzer_levels))
    return analyzer_levels


def get() -> dict:
    log.debug("Analyzer level configuration requested")
    return _analyzer_configs


def map_level(analyzer_name: str, observable_type: str, level: str) -> str:
    if not isinstance(analyzer_name, str):
        log.error("Invalid analyzer_name type for level mapping: %s", type(analyzer_name).__name__)
        raise TypeError("analyzer_name must be a string")
    if not isinstance(observable_type, str):
        log.error("Invalid observable_type type for level mapping: %s", type(observable_type).__name__)
        raise TypeError("observable_type must be a string")
    if not isinstance(level, str):
        log.error("Invalid level type for level mapping: %s", type(level).__name__)
        raise TypeError("level must be a string")

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


_analyzer_configs: dict = _verify_config(config.get_analyzer_level_mappings())
