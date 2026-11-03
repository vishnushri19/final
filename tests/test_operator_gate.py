from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
SRC_ROOT = PROJECT_ROOT / "src"
for path in (str(SCRIPTS_ROOT), str(SRC_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from run_upgrade_node import (  # noqa: E402
    post_upgrade_stabilization_seconds,
    require_operator_go_ahead,
)


class OperatorGateTests(unittest.TestCase):
    def test_records_approved_gate(self):
        with patch("builtins.input", return_value="y"):
            result = require_operator_go_ahead("CRQ123")

        self.assertEqual("PASS", result.status)
        self.assertTrue(result.details["approved"])

    def test_blocks_declined_gate(self):
        with patch("builtins.input", return_value=""):
            result = require_operator_go_ahead("CRQ123")

        self.assertEqual("FAIL", result.status)
        self.assertFalse(result.details["approved"])


class PostUpgradeStabilizationTests(unittest.TestCase):
    def test_defaults_to_five_minutes(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(300, post_upgrade_stabilization_seconds())

    def test_allows_explicit_override(self):
        with patch.dict(
            "os.environ",
            {"POST_UPGRADE_STABILIZATION_SECONDS": "420"},
            clear=True,
        ):
            self.assertEqual(420, post_upgrade_stabilization_seconds())

    def test_rejects_negative_duration(self):
        with patch.dict(
            "os.environ",
            {"POST_UPGRADE_STABILIZATION_SECONDS": "-1"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "cannot be negative"):
                post_upgrade_stabilization_seconds()


if __name__ == "__main__":
    unittest.main()
