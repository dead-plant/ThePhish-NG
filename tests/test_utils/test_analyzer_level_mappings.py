import importlib
import sys
import unittest
from unittest.mock import patch

from app import config


MODULE_NAME = "app.utils.analyzer_level_mappings"


def import_with_analyzer_config(analyzer_config):
    sys.modules.pop(MODULE_NAME, None)
    with patch.object(config, "get_analyzer_level_mappings", return_value=analyzer_config):
        return importlib.import_module(MODULE_NAME)


class AnalyzerLevelMappingsTests(unittest.TestCase):
    def test_map_level_uses_injected_config(self):
        module = import_with_analyzer_config(
            {
                "version": 1,
                "RiskyAnalyzer_1_0": {
                    "dataType": ["url", "domain"],
                    "levelMapping": {
                        "malicious": "suspicious",
                        "suspicious": "info",
                    },
                },
            }
        )

        self.assertEqual(module.map_level("RiskyAnalyzer_1_0", "url", "malicious"), "suspicious")
        self.assertEqual(module.map_level("RiskyAnalyzer_1_0", "domain", "suspicious"), "info")

    def test_map_level_keeps_level_when_no_mapping_applies(self):
        module = import_with_analyzer_config(
            {
                "version": 1,
                "RiskyAnalyzer_1_0": {
                    "dataType": ["url"],
                    "levelMapping": {"malicious": "suspicious"},
                },
            }
        )

        self.assertEqual(module.map_level("UnknownAnalyzer_1_0", "url", "malicious"), "malicious")
        self.assertEqual(module.map_level("RiskyAnalyzer_1_0", "mail", "malicious"), "malicious")
        self.assertEqual(module.map_level("RiskyAnalyzer_1_0", "url", "safe"), "safe")
        self.assertEqual(module.map_level("__proto__", "url", "malicious"), "malicious")
        self.assertEqual(module.map_level("RiskyAnalyzer_1_0", "../../../etc/passwd", "malicious"), "malicious")

    def test_map_level_leaves_untrusted_string_payloads_unchanged(self):
        module = import_with_analyzer_config(
            {
                "version": 1,
                "RiskyAnalyzer_1_0": {
                    "dataType": ["url"],
                    "levelMapping": {"malicious": "suspicious"},
                },
            }
        )

        payloads = [
            ("RiskyAnalyzer_1_0\x00", "url", "malicious"),
            ("RiskyAnalyzer_1_0", "URL", "malicious"),
            ("RiskyAnalyzer_1_0", "url ", "malicious"),
            ("RiskyAnalyzer_1_0", "url", "malicious\nsafe"),
            ("RiskyAnalyzer_1_0", "url", "../../malicious"),
            ("RiskyAnalyzer_1_0", "url", "__proto__"),
        ]

        for analyzer_name, observable_type, level in payloads:
            with self.subTest(analyzer_name=analyzer_name, observable_type=observable_type, level=level):
                self.assertEqual(module.map_level(analyzer_name, observable_type, level), level)

    def test_get_excludes_version_metadata(self):
        module = import_with_analyzer_config(
            {
                "version": 1,
                "RiskyAnalyzer_1_0": {
                    "dataType": ["url"],
                    "levelMapping": {"malicious": "suspicious"},
                },
            }
        )

        self.assertEqual(
            module.get(),
            {
                "RiskyAnalyzer_1_0": {
                    "dataType": ["url"],
                    "levelMapping": {"malicious": "suspicious"},
                },
            },
        )

    def test_map_level_rejects_non_string_arguments(self):
        module = import_with_analyzer_config(
            {
                "version": 1,
                "RiskyAnalyzer_1_0": {
                    "dataType": ["url"],
                    "levelMapping": {"malicious": "suspicious"},
                },
            }
        )

        invalid_calls = [
            (123, "url", "malicious"),
            (["RiskyAnalyzer_1_0"], "url", "malicious"),
            ("RiskyAnalyzer_1_0", None, "malicious"),
            ("RiskyAnalyzer_1_0", {"type": "url"}, "malicious"),
            ("RiskyAnalyzer_1_0", "url", 1),
            ("RiskyAnalyzer_1_0", "url", b"malicious"),
        ]

        for analyzer_name, observable_type, level in invalid_calls:
            with self.subTest(analyzer_name=analyzer_name, observable_type=observable_type, level=level):
                with self.assertRaises(TypeError):
                    module.map_level(analyzer_name, observable_type, level)

    def test_import_rejects_invalid_injected_config(self):
        invalid_configs = [
            [],
            {1: {"dataType": ["url"], "levelMapping": {"malicious": "suspicious"}}},
            {"Analyzer": []},
            {"Analyzer": {"dataType": "url", "levelMapping": {}}},
            {"Analyzer": {"dataType": ["url", 1], "levelMapping": {}}},
            {"Analyzer": {"dataType": ["url"], "levelMapping": []}},
            {"Analyzer": {"dataType": ["url"], "levelMapping": {"malicious": 1}}},
        ]

        for invalid_config in invalid_configs:
            with self.subTest(invalid_config=invalid_config):
                with self.assertRaises(ValueError):
                    import_with_analyzer_config(invalid_config)


if __name__ == "__main__":
    unittest.main()
