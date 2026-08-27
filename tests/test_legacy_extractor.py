from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "extract_legacy.py"
SPEC = importlib.util.spec_from_file_location("extract_legacy", MODULE_PATH)
assert SPEC and SPEC.loader
extract_legacy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = extract_legacy
SPEC.loader.exec_module(extract_legacy)


class LiteralParserTests(unittest.TestCase):
    def test_parses_supported_javascript_literal_without_execution(self) -> None:
        value = extract_legacy.LiteralParser("{key:'valor', list:[1,true,null,], nested:{'x-y':2},}").parse()
        self.assertEqual(value, {"key": "valor", "list": [1, True, None], "nested": {"x-y": 2}})

    def test_rejects_executable_identifier(self) -> None:
        with self.assertRaises(extract_legacy.LiteralSyntaxError):
            extract_legacy.LiteralParser("{value:process}").parse()

    def test_rejects_template_interpolation(self) -> None:
        with self.assertRaises(extract_legacy.LiteralSyntaxError):
            extract_legacy.LiteralParser("`${danger}`").parse()


if __name__ == "__main__":
    unittest.main()
