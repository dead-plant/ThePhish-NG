import itertools
import json
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app import config


TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
_TEMP_COUNTER = itertools.count()

VALID_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "null": {
            "class": "logging.NullHandler",
        },
    },
    "root": {
        "handlers": ["null"],
        "level": "INFO",
    },
}

VALID_APP_CONFIG = """\
version = 1

[server]
bind_addr = "127.0.0.1"
port = 8080
"""

VALID_WHITELIST = {
    "version": 1,
    "exactMatching": {
        "mail": [],
        "ip": ["127.0.0.1"],
        "domain": [],
        "url": [],
        "filename": [],
        "filetype": [],
        "hash": [],
    },
    "regexMatching": {
        "mail": [],
        "ip": [],
        "domain": [],
        "url": [],
        "filename": [],
    },
}

VALID_ANALYZER_LEVEL_MAPPINGS = {
    "version": 1,
    "Analyzer_1_0": {
        "dataType": ["url"],
        "levelMapping": {
            "malicious": "suspicious",
        },
    },
}


@contextmanager
def temporary_directory():
    TEST_TMP_ROOT.mkdir(exist_ok=True)
    path = TEST_TMP_ROOT / "config-loader-{}".format(next(_TEMP_COUNTER))
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def tearDownModule():
    if TEST_TMP_ROOT.exists():
        shutil.rmtree(TEST_TMP_ROOT, ignore_errors=True)


def reset_config_state():
    config._app_config = None
    config._whitelist = None
    config._analyzer_level_mappings = None


def write_config_dir(
    root: Path,
    logging_config=VALID_LOGGING_CONFIG,
    app_config=VALID_APP_CONFIG,
    whitelist=VALID_WHITELIST,
    analyzer_level_mappings=VALID_ANALYZER_LEVEL_MAPPINGS,
):
    if logging_config is not None:
        (root / config.LOGGING_FILE).write_text(json.dumps(logging_config), encoding="utf-8")
    if app_config is not None:
        (root / config.APP_CONF_FILE).write_text(app_config, encoding="utf-8")
    if whitelist is not None:
        (root / config.WHITELIST_FILE).write_text(json.dumps(whitelist), encoding="utf-8")
    if analyzer_level_mappings is not None:
        (root / config.ANALYZER_LEVEL_MAPPINGS_FILE).write_text(
            json.dumps(analyzer_level_mappings),
            encoding="utf-8",
        )


class ConfigLoaderTests(unittest.TestCase):
    def setUp(self):
        reset_config_state()

    def tearDown(self):
        reset_config_state()

    def test_init_loads_all_config_files_and_caches_values(self):
        with temporary_directory() as tmp_dir:
            config_dir = Path(tmp_dir)
            write_config_dir(config_dir)

            with patch.object(config.logging.config, "dictConfig") as dict_config:
                config.init(config_dir)

        dict_config.assert_called_once_with(VALID_LOGGING_CONFIG)
        self.assertEqual(config.get_app_config()["server"]["bind_addr"], "127.0.0.1")
        self.assertEqual(config.get_app_config()["server"]["port"], 8080)
        self.assertEqual(config.get_whitelist(), VALID_WHITELIST)
        self.assertEqual(config.get_analyzer_level_mappings(), VALID_ANALYZER_LEVEL_MAPPINGS)

    def test_init_rejects_missing_config_directory(self):
        with temporary_directory() as tmp_dir:
            missing_dir = Path(tmp_dir) / "missing"

            with self.assertRaises(config.ConfigError) as error:
                config.init(missing_dir)

        self.assertIn("Config directory", str(error.exception))
        self.assertIn("does not exist", str(error.exception))

    def test_init_rejects_missing_required_files(self):
        required_files = [
            config.LOGGING_FILE,
            config.APP_CONF_FILE,
            config.WHITELIST_FILE,
            config.ANALYZER_LEVEL_MAPPINGS_FILE,
        ]

        for missing_file in required_files:
            with self.subTest(missing_file=missing_file):
                reset_config_state()
                with temporary_directory() as tmp_dir:
                    config_dir = Path(tmp_dir)
                    write_config_dir(config_dir)
                    (config_dir / missing_file).unlink()

                    with patch.object(config.logging.config, "dictConfig"):
                        with self.assertRaises(config.ConfigError) as error:
                            config.init(config_dir)

                self.assertIn(missing_file, str(error.exception))
                self.assertIn("does not exist", str(error.exception))

    def test_init_rejects_invalid_file_syntax(self):
        invalid_cases = [
            (config.LOGGING_FILE, "{"),
            (config.APP_CONF_FILE, "version = "),
            (config.WHITELIST_FILE, "{"),
            (config.ANALYZER_LEVEL_MAPPINGS_FILE, "{"),
        ]

        for filename, invalid_content in invalid_cases:
            with self.subTest(filename=filename):
                reset_config_state()
                with temporary_directory() as tmp_dir:
                    config_dir = Path(tmp_dir)
                    write_config_dir(config_dir)
                    (config_dir / filename).write_text(invalid_content, encoding="utf-8")

                    with patch.object(config.logging.config, "dictConfig"):
                        with self.assertRaises(config.ConfigError) as error:
                            config.init(config_dir)

                self.assertIn(filename, str(error.exception))
                self.assertIn("is not valid", str(error.exception))

    def test_init_rejects_invalid_logging_configuration(self):
        with temporary_directory() as tmp_dir:
            config_dir = Path(tmp_dir)
            write_config_dir(config_dir)

            with patch.object(config.logging.config, "dictConfig", side_effect=ValueError("bad logging")):
                with self.assertRaises(config.ConfigError) as error:
                    config.init(config_dir)

        self.assertIn("is not a valid logging configuration", str(error.exception))
        self.assertIn("bad logging", str(error.exception))

    def test_init_rejects_outdated_versions(self):
        invalid_cases = [
            (config.APP_CONF_FILE, 'version = 2\n\n[server]\nbind_addr = "127.0.0.1"\nport = 8080\n'),
            (config.WHITELIST_FILE, {**VALID_WHITELIST, "version": 2}),
            (config.ANALYZER_LEVEL_MAPPINGS_FILE, {**VALID_ANALYZER_LEVEL_MAPPINGS, "version": 2}),
        ]

        for filename, invalid_config in invalid_cases:
            with self.subTest(filename=filename):
                reset_config_state()
                with temporary_directory() as tmp_dir:
                    config_dir = Path(tmp_dir)
                    write_config_dir(config_dir)
                    if isinstance(invalid_config, str):
                        (config_dir / filename).write_text(invalid_config, encoding="utf-8")
                    else:
                        (config_dir / filename).write_text(json.dumps(invalid_config), encoding="utf-8")

                    with patch.object(config.logging.config, "dictConfig"):
                        with self.assertRaises(config.ConfigError) as error:
                            config.init(config_dir)

                self.assertIn(filename, str(error.exception))
                self.assertIn("outdated", str(error.exception))

    def test_read_file_wraps_os_errors(self):
        unreadable_path = Path("unreadable.json")

        with patch.object(Path, "is_file", return_value=True):
            with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
                with self.assertRaises(config.ConfigError) as error:
                    config._read_file(unreadable_path)

        self.assertIn("is not readable", str(error.exception))


if __name__ == "__main__":
    unittest.main()
