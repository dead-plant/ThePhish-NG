import importlib
import sys
import unittest
from copy import deepcopy
from unittest.mock import patch

from app import config


MODULE_NAME = "app.utils.whitelist"


BASE_WHITELIST_CONFIG = {
    "version": 1,
    "exactMatching": {
        "mail": ["trusted@example.com"],
        "ip": ["127.0.0.1"],
        "domain": ["trusted.example"],
        "url": ["https://safe.example/login"],
        "filename": ["readme.txt"],
        "filetype": ["pdf"],
        "hash": ["abc123"],
    },
    "regexMatching": {
        "mail": [r".*@trusted\.example$"],
        "ip": [r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"],
        "domain": [r"(^|\.)trusted\.example$"],
        "url": [r"^https://safe\.example/"],
        "filename": [r"^invoice_\d+\.pdf$"],
    },
}


def import_with_whitelist_config(whitelist_config):
    sys.modules.pop(MODULE_NAME, None)
    with patch.object(config, "get_whitelist", return_value=whitelist_config):
        return importlib.import_module(MODULE_NAME)


class WhitelistTests(unittest.TestCase):
    def test_is_whitelisted_uses_exact_matches_from_injected_config(self):
        module = import_with_whitelist_config(deepcopy(BASE_WHITELIST_CONFIG))

        self.assertTrue(module.is_whitelisted("mail", " TRUSTED@EXAMPLE.COM "))
        self.assertTrue(module.is_whitelisted("ip", "127.0.0.1"))
        self.assertTrue(module.is_whitelisted("domain", "trusted.example"))
        self.assertTrue(module.is_whitelisted("url", "https://safe.example/login"))
        self.assertTrue(module.is_whitelisted("filename", "readme.txt"))
        self.assertTrue(module.is_whitelisted("filetype", "pdf"))
        self.assertTrue(module.is_whitelisted("hash", "abc123"))

    def test_is_whitelisted_uses_regex_matches_from_injected_config(self):
        module = import_with_whitelist_config(deepcopy(BASE_WHITELIST_CONFIG))

        self.assertTrue(module.is_whitelisted("mail", "admin@trusted.example"))
        self.assertTrue(module.is_whitelisted("ip", "10.1.2.3"))
        self.assertTrue(module.is_whitelisted("domain", "sub.trusted.example"))
        self.assertTrue(module.is_whitelisted("url", "https://safe.example/path"))
        self.assertTrue(module.is_whitelisted("filename", "invoice_123.pdf"))

    def test_is_whitelisted_returns_false_for_unlisted_observable(self):
        module = import_with_whitelist_config(deepcopy(BASE_WHITELIST_CONFIG))

        self.assertFalse(module.is_whitelisted("mail", "attacker@example.com"))
        self.assertFalse(module.is_whitelisted("ip", "8.8.8.8"))
        self.assertFalse(module.is_whitelisted("hash", "def456"))
        self.assertFalse(module.is_whitelisted("url", "javascript:alert(1)"))
        self.assertFalse(module.is_whitelisted("filename", "../../trusted.example"))
        self.assertFalse(module.is_whitelisted("domain", "trusted.example.evil"))

    def test_is_whitelisted_rejects_untrusted_strings_that_contain_safe_values(self):
        module = import_with_whitelist_config(deepcopy(BASE_WHITELIST_CONFIG))

        payloads = [
            ("mail", "trusted@example.com.evil"),
            ("mail", "trusted@example.com\nattacker@example.com"),
            ("ip", "127.0.0.1.evil"),
            ("domain", "eviltrusted.example"),
            ("url", "https://safe.example.evil/login"),
            ("filename", "../readme.txt"),
            ("filetype", "pdf.exe"),
            ("hash", "abc123;rm -rf /"),
        ]

        for obs_type, obs_value in payloads:
            with self.subTest(obs_type=obs_type, obs_value=obs_value):
                self.assertFalse(module.is_whitelisted(obs_type, obs_value))

    def test_is_whitelisted_rejects_invalid_arguments(self):
        module = import_with_whitelist_config(deepcopy(BASE_WHITELIST_CONFIG))

        invalid_types = [123, b"mail", ["mail"], {"type": "mail"}, "asn", "Mail"]
        for obs_type in invalid_types:
            with self.subTest(obs_type=obs_type):
                with self.assertRaises(module.UnsupportedObservableError):
                    module.is_whitelisted(obs_type, "trusted@example.com")

        invalid_values = [None, 123, b"trusted@example.com", ["trusted@example.com"], {}, "   ", "\t\n", ""]
        for obs_value in invalid_values:
            with self.subTest(obs_value=obs_value):
                with self.assertRaises(module.ObservableValueError):
                    module.is_whitelisted("mail", obs_value)

    def test_import_rejects_invalid_injected_config(self):
        invalid_configs = [
            [],
            {"exactMatching": {}, "regexMatching": deepcopy(BASE_WHITELIST_CONFIG["regexMatching"])},
            {
                "exactMatching": {
                    **deepcopy(BASE_WHITELIST_CONFIG["exactMatching"]),
                    "mail": "trusted@example.com",
                },
                "regexMatching": deepcopy(BASE_WHITELIST_CONFIG["regexMatching"]),
            },
            {
                "exactMatching": {
                    **deepcopy(BASE_WHITELIST_CONFIG["exactMatching"]),
                    "mail": [1],
                },
                "regexMatching": deepcopy(BASE_WHITELIST_CONFIG["regexMatching"]),
            },
            {
                "exactMatching": deepcopy(BASE_WHITELIST_CONFIG["exactMatching"]),
                "regexMatching": {
                    **deepcopy(BASE_WHITELIST_CONFIG["regexMatching"]),
                    "mail": ["["],
                },
            },
            {
                "exactMatching": deepcopy(BASE_WHITELIST_CONFIG["exactMatching"]),
                "regexMatching": {
                    **deepcopy(BASE_WHITELIST_CONFIG["regexMatching"]),
                    "url": "safe.example",
                },
            },
            {
                "exactMatching": deepcopy(BASE_WHITELIST_CONFIG["exactMatching"]),
                "regexMatching": {
                    **deepcopy(BASE_WHITELIST_CONFIG["regexMatching"]),
                    "filename": [1],
                },
            },
        ]

        for invalid_config in invalid_configs:
            with self.subTest(invalid_config=invalid_config):
                with self.assertRaises(ValueError):
                    import_with_whitelist_config(invalid_config)


if __name__ == "__main__":
    unittest.main()
