import logging
from app import config

log = logging.getLogger(__name__)


def _verify_config(analyzer_levels: dict) -> dict:
    if not isinstance(analyzer_levels, dict):
        raise ValueError("expected a JSON object at the top level")

    verified_analyzer_levels = {}
    for analyzer_name, analyzer_conf in analyzer_levels.items():
        if analyzer_name == 'version':
            continue
        if not isinstance(analyzer_name, str):
            raise ValueError("analyzer names must be strings")
        if not isinstance(analyzer_conf, dict):
            raise ValueError("entry '{}' must be a JSON object".format(analyzer_name))
        if not isinstance(analyzer_conf.get('dataType'), list):
            raise ValueError("entry '{}.dataType' must be a list".format(analyzer_name))
        if not all(isinstance(data_type, str) for data_type in analyzer_conf.get('dataType')):
            raise ValueError("entry '{}.dataType' must contain only strings".format(analyzer_name))
        if not isinstance(analyzer_conf.get('levelMapping'), dict):
            raise ValueError("entry '{}.levelMapping' must be a JSON object".format(analyzer_name))
        if not all(isinstance(source, str) and isinstance(target, str) for source, target in analyzer_conf.get('levelMapping').items()):
            raise ValueError("entry '{}.levelMapping' must contain only string keys and values".format(analyzer_name))
        log.debug(
            "Validated analyzer level config for %s: data_type_count=%d, mapped_level_count=%d",
            analyzer_name,
            len(analyzer_conf.get('dataType', [])),
            len(analyzer_conf.get('levelMapping', {})),
        )
        verified_analyzer_levels[analyzer_name] = analyzer_conf

    log.info("Analyzer level configuration verified for %d analyzers", len(verified_analyzer_levels))
    return verified_analyzer_levels


def get() -> dict:
    return _analyzer_configs


def map_level(analyzer_name: str, observable_type: str, level: str) -> str:
    if not isinstance(analyzer_name, str):
        raise TypeError("analyzer_name must be a string")
    if not isinstance(observable_type, str):
        raise TypeError("observable_type must be a string")
    if not isinstance(level, str):
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


try:
    _analyzer_configs: dict = _verify_config(config.get_analyzer_level_mappings())
except Exception as exc:
    log.error("Failed to load analyzer level mapping configuration.", exc_info=exc)
    raise exc
