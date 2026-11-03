from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
SRC_ROOT = PROJECT_ROOT / "src"
for path in (str(SCRIPTS_ROOT), str(SRC_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from resume_upgrade_node import (  # noqa: E402
    _backup_set_is_complete,
    _stage2_retry_required,
)


class ResumeBackupSetTests(unittest.TestCase):
    def test_requires_ucs_scf_archive_and_qkview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            backups_dir = Path(temp_dir)
            (backups_dir / "node.ucs").touch()
            (backups_dir / "node.tar").touch()

            self.assertFalse(_backup_set_is_complete(backups_dir))

            (backups_dir / "node.qkview").touch()

            self.assertTrue(_backup_set_is_complete(backups_dir))


class ResumeStageEvidenceTests(unittest.TestCase):
    def write_report(self, directory: Path, results: list[dict]) -> Path:
        path = directory / "upgrade_flow_report.json"
        path.write_text(json.dumps({"results": results}), encoding="utf-8")
        return path

    def test_retries_stage2_when_upload_failed_before_install_submission(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.write_report(
                Path(temp_dir),
                [{"id": "EXEC-UPLOAD-ISO-001", "status": "FAIL"}],
            )

            retry, reason = _stage2_retry_required(path)

        self.assertTrue(retry)
        self.assertIn("No install submission", reason)

    def test_allows_reboot_only_after_recorded_install_submission(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.write_report(
                Path(temp_dir),
                [{"id": "EXEC-INSTALL-001", "status": "PASS"}],
            )

            retry, _ = _stage2_retry_required(path)

        self.assertFalse(retry)

    def test_blocks_failed_install_submission(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.write_report(
                Path(temp_dir),
                [{"id": "EXEC-INSTALL-001", "status": "FAIL"}],
            )

            with self.assertRaisesRegex(ValueError, "did not pass"):
                _stage2_retry_required(path)


if __name__ == "__main__":
    unittest.main()
