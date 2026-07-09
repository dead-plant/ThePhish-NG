"""Application configuration: loading, validation, and global access.

Call init() exactly once at startup (see run.py). Afterward any module can
read configuration through the accessor functions without touching the disk.
"""
from typing import Optional

import json
import logging
import logging.config
from dataclasses import dataclass
from pathlib import Path
import tomllib

log = logging.getLogger(__name__)

# --- Filenames --------------------------------------------------------------
LOGGING_FILE = "logging.json"
APP_CONF_FILE = "app.conf"
WHITELIST_FILE = "whitelist.json"
ANALYZER_LEVEL_MAPPINGS_FILE = "analyzer_level_mappings.json"

# --- Expected schema versions -----------------------------------------------
EXPECTED_VERSIONS = {
    APP_CONF_FILE: 1,
    WHITELIST_FILE: 1,
    ANALYZER_LEVEL_MAPPINGS_FILE: 1,
}

EXAMPLE_CONFIG = "https://github.com/dead-plant/ThePhish-NG/tree/master/config-example"

class ConfigError(Exception):
    """Raised when a config file is missing, unreadable, invalid, or outdated."""

# --- Module-level state, populated once by init() ---------------------------
_app_config: Optional[dict] = None
_whitelist: Optional[dict] = None
_analyzer_level_mappings: Optional[dict] = None


def _require(value, name):
    if value is None:
        raise RuntimeError(
            f"Configuration not initialized: {name} requested before config.init() ran."
        )
    return value


def get_app_config() -> dict:
    return _require(_app_config, "app config")


def get_whitelist() -> dict:
    """Return the whole whitelist.json content. Treat as read-only."""
    return _require(_whitelist, "whitelist")


def get_analyzer_level_mappings() -> dict:
    """Return the whole analyzer_level_mappings.json content. Treat as read-only."""
    return _require(_analyzer_level_mappings, "analyzer level mappings")


# --- Loading helpers --------------------------------------------------------
def _read_file(path: Path) -> str:
    if not path.is_file():
        raise ConfigError(
            f"{path} does not exist. "
            f"Please see {EXAMPLE_CONFIG} for a valid configuration example."
        )
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path} is not readable ({exc.strerror}). Please check file permissions.") from exc


def _load_json(path: Path) -> dict:
    try:
        return json.loads(_read_file(path))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"{path} is not valid JSON ({exc}). "
            f"Please see {EXAMPLE_CONFIG}/{path.name} for a valid example."
        ) from exc


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(_read_file(path))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"{path} is not valid TOML ({exc}). "
            f"Please see {EXAMPLE_CONFIG}/{path.name} for a valid example."
        ) from exc


def _check_version(path: Path, data: dict, expected: int) -> None:
    found = data.get("version")
    if found != expected:
        raise ConfigError(
            f"Your {path.name} config is outdated (found version {found!r}, expected {expected}). "
            f"Please migrate your config to the new version. See example in {EXAMPLE_CONFIG}/{path.name}."
        )


def _init_logging(path: Path) -> None:
    config = _load_json(path)  # syntax validation
    try:
        logging.config.dictConfig(config)
    except (ValueError, TypeError, AttributeError, ImportError, KeyError) as exc:
        raise ConfigError(
            f"{path} is not a valid logging configuration ({exc}). "
            f"Please see {EXAMPLE_CONFIG}/{LOGGING_FILE} for a valid example."
        ) from exc


def _load_versioned_toml(path: Path, expected_version: int) -> dict:
    data = _load_toml(path)              # 1. syntax
    _check_version(path, data, EXPECTED_VERSIONS[APP_CONF_FILE])  # 2. version
    return data


def _load_versioned_json(path: Path, expected_version: int) -> dict:
    data = _load_json(path)             # 1. syntax
    _check_version(path, data, expected_version)  # 2. version
    return data


def init(config_dir: Path) -> None:
    """Load, validate, and cache all configuration.

    Call once before the rest of the app starts. Raises ConfigError with a
    user-facing message on any problem.
    """
    global _app_config, _whitelist, _analyzer_level_mappings

    config_dir = config_dir.resolve()
    if not config_dir.is_dir():
        raise ConfigError(
            f"Config directory {config_dir} does not exist. "
            f"Please see {EXAMPLE_CONFIG} for a valid configuration example."
        )

    # 1. Logging first, so the steps below can log.
    _init_logging(config_dir / LOGGING_FILE)
    log.info("Loaded %s", LOGGING_FILE)

    # 2. app.conf -> bind address + port.
    _app_config = _load_versioned_toml(config_dir / APP_CONF_FILE, EXPECTED_VERSIONS[APP_CONF_FILE])
    log.info("Loaded %s", APP_CONF_FILE)

    # 3. Data files consumed wholesale by other modules.
    _whitelist = _load_versioned_json(config_dir / WHITELIST_FILE, EXPECTED_VERSIONS[WHITELIST_FILE])
    log.info("Loaded %s", WHITELIST_FILE)

    _analyzer_level_mappings = _load_versioned_json(config_dir / ANALYZER_LEVEL_MAPPINGS_FILE, EXPECTED_VERSIONS[ANALYZER_LEVEL_MAPPINGS_FILE])
    log.info("Loaded %s", ANALYZER_LEVEL_MAPPINGS_FILE)
