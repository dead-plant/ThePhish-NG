import logging
import re
from app import config

log = logging.getLogger(__name__)

_OBSERVABLE_TYPES = {'mail', 'ip', 'domain', 'url', 'filename', 'filetype', 'hash'}

class UnsupportedObservableError(Exception):
    """Raised when an observable type is not supported."""

class ObservableValueError(Exception):
    """Raised when the type of the observable value is not a string or when the value is empty."""

def _require_list(whitelist_dict: dict, field_path: str) -> list:
    current = whitelist_dict
    for key in field_path.split('.'):
        if not isinstance(current, dict) or key not in current:
            log.error("Whitelist validation failed: missing required field '%s'", field_path)
            raise ValueError("missing required field '{}'".format(field_path))
        current = current[key]
    if not isinstance(current, list):
        log.error("Whitelist validation failed: field '%s' must be a list, got %s", field_path, type(current).__name__)
        raise ValueError("field '{}' must be a list".format(field_path))
    return current

def _require_string_list(whitelist_dict: dict, field_path: str) -> list:
    values = _require_list(whitelist_dict, field_path)
    if not all(isinstance(value, str) for value in values):
        log.error("Whitelist validation failed: field '%s' contains non-string values", field_path)
        raise ValueError("field '{}' must contain only strings".format(field_path))
    log.debug("Validated whitelist field '%s' with %d entries", field_path, len(values))
    return values

def _validate_regexes(whitelist: dict):
    for field_path, whitelist_key in [
        ('regexMatching.mail', 'mailRegex'),
        ('regexMatching.ip', 'ipRegex'),
        ('regexMatching.domain', 'domainRegex'),
        ('regexMatching.url', 'urlRegex'),
        ('regexMatching.filename', 'filenameRegex'),
    ]:
        for regex_pattern in whitelist[whitelist_key]:
            try:
                re.compile(regex_pattern)
            except re.error as e:
                log.error("Whitelist validation failed: invalid regex in '%s': %s", field_path, e)
                raise ValueError("field '{}' contains invalid regex '{}': {}".format(field_path, regex_pattern, e)) from e
        log.debug("Validated %d regex whitelist entries for '%s'", len(whitelist[whitelist_key]), field_path)

def _build_whitelist(whitelist_dict: dict) -> dict:
    # Build the whitelist from the configured parts:
    # - The exact matching part
    # - The regex matching part
    # - Three lists of domains that are used to whitelist subdomains, URLs and email addresses that contain them
    if not isinstance(whitelist_dict, dict):
        log.error("Whitelist initialization failed: expected top-level JSON object, got %s", type(whitelist_dict).__name__)
        raise ValueError("expected a JSON object at the top level")

    whitelist = {}
    whitelist['mailExact'] = _require_string_list(whitelist_dict, 'exactMatching.mail')
    whitelist['mailRegex'] = _require_string_list(whitelist_dict, 'regexMatching.mail')
    whitelist['ipExact'] = _require_string_list(whitelist_dict, 'exactMatching.ip')
    whitelist['ipRegex'] = _require_string_list(whitelist_dict, 'regexMatching.ip')
    whitelist['domainExact'] = _require_string_list(whitelist_dict, 'exactMatching.domain')
    whitelist['domainRegex'] = _require_string_list(whitelist_dict, 'regexMatching.domain')
    whitelist['urlExact'] = _require_string_list(whitelist_dict, 'exactMatching.url')
    whitelist['urlRegex'] = _require_string_list(whitelist_dict, 'regexMatching.url')
    whitelist['filenameExact'] = _require_string_list(whitelist_dict, 'exactMatching.filename')
    whitelist['filenameRegex'] = _require_string_list(whitelist_dict, 'regexMatching.filename')
    whitelist['filetypeExact'] = _require_string_list(whitelist_dict, 'exactMatching.filetype')
    whitelist['hashExact'] = _require_string_list(whitelist_dict, 'exactMatching.hash')

    _validate_regexes(whitelist)
    log.debug(
        "Built whitelist: exact_counts=%s, regex_counts=%s",
        {
            'mail': len(whitelist['mailExact']),
            'ip': len(whitelist['ipExact']),
            'domain': len(whitelist['domainExact']),
            'url': len(whitelist['urlExact']),
            'filename': len(whitelist['filenameExact']),
            'filetype': len(whitelist['filetypeExact']),
            'hash': len(whitelist['hashExact']),
        },
        {
            'mail': len(whitelist['mailRegex']),
            'ip': len(whitelist['ipRegex']),
            'domain': len(whitelist['domainRegex']),
            'url': len(whitelist['urlRegex']),
            'filename': len(whitelist['filenameRegex']),
        },
    )

    log.info("Finished building whitelist")
    return whitelist

def get() -> dict:
    log.debug("Whitelist requested")
    return _whitelist

def is_whitelisted(obs_type: str, obs_value) -> bool:
    # Check if an observable is whitelisted with an exact match or with a regex match
    whitelist = get()

    if not isinstance(obs_type, str):
        log.error("Invalid whitelist observable type argument: expected string, got %s", type(obs_type).__name__)
        raise UnsupportedObservableError("obs_type must be a string")
    if obs_type not in _OBSERVABLE_TYPES:
        log.error("Unsupported whitelist observable type requested: %s", obs_type)
        raise UnsupportedObservableError("unsupported whitelist observable type '{}'".format(obs_type))
    if not isinstance(obs_value, str):
        log.error(
            "Invalid whitelist observable value for type '%s': expected string, got %s",
            obs_type,
            type(obs_value).__name__,
        )
        raise ObservableValueError("obs_value must be a string")

    obs_value = obs_value.lower().strip()

    if not obs_value:
        log.error("Invalid whitelist observable value for type '%s': value is empty", obs_type)
        raise ObservableValueError("Invalid whitelist observable value for type '{}': value is empty".format(obs_type))

    found = False
    if (not found) and (obs_value in whitelist[obs_type + 'Exact']):
        found = True
        log.debug("Observable whitelisted by exact match: type=%s, value=%s", obs_type, obs_value)

    if (not found) and (obs_type not in ['hash', 'filetype']):
        for regex in whitelist[obs_type+'Regex']:
            if re.search(regex, obs_value):
                found = True
                log.debug("Observable whitelisted by regex match: type=%s, value=%s, regex=%s", obs_type, obs_value, regex)
                break
    if not found:
        log.debug("Observable not whitelisted: type=%s, value=%s", obs_type, obs_value)
    return found

_whitelist = _build_whitelist(config.get_whitelist())
