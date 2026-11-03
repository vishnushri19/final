from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from f5upgrade.rollback import (  # noqa: E402
    VolumeEvidence,
    pre_upgrade_volume_from_report,
    validate_rollback_candidate,
)


def volume(
    name: str,
    *,
    active: bool,
    version: str = "17.5.1.3",
    build: str = "0.192.19",
    status: str = "complete",
) -> VolumeEvidence:
    return VolumeEvidence(
        volume=name,
        version=version,
        build=build,
        status=status,
        active=active,
    )


class PreUpgradeVolumeTests(unittest.TestCase):
    def test_selects_saved_active_completed_volume(self):
        report = {
            "results": [
                {
                    "id": "RB-001",
                    "details": {
                        "software_volumes": {
                            "items": [
                                {
                                    "name": "HD1.1",
                                    "version": "17.5.1.3",
                                    "build": "0.192.19",
                                    "status": "complete",
                                    "active": True,
                                },
                                {
                                    "name": "HD1.2",
                                    "version": "17.5.1.9",
                                    "build": "0.0.12",
                                    "status": "complete",
                                },
                            ]
                        }
                    },
                }
            ]
        }

        selected = pre_upgrade_volume_from_report(report)

        self.assertEqual("HD1.1", selected.volume)
        self.assertEqual("17.5.1.3", selected.version)


class RollbackCandidateValidationTests(unittest.TestCase):
    def test_allows_matching_inactive_pre_upgrade_volume_on_standby(self):
        expected = volume("HD1.1", active=True)
        live = [
            volume("HD1.1", active=False),
            volume(
                "HD1.2",
                active=True,
                version="17.5.1.9",
                build="0.0.12",
            ),
        ]

        self.assertEqual([], validate_rollback_candidate(expected, live, "standby"))

    def test_blocks_changed_or_installing_volume(self):
        expected = volume("HD1.1", active=True)
        live = [
            volume(
                "HD1.1",
                active=False,
                version="17.5.1.4",
                status="installing 42 pct",
            ),
            volume(
                "HD1.2",
                active=True,
                version="17.5.1.9",
                build="0.0.12",
            ),
        ]

        failures = validate_rollback_candidate(expected, live, "standby")

        self.assertTrue(
            any("Installation is still in progress" in failure for failure in failures)
        )
        self.assertTrue(
            any("no longer matches saved version/build" in failure for failure in failures)
        )

    def test_blocks_active_device(self):
        expected = volume("HD1.1", active=True)
        live = [
            volume("HD1.1", active=False),
            volume(
                "HD1.2",
                active=True,
                version="17.5.1.9",
                build="0.0.12",
            ),
        ]

        failures = validate_rollback_candidate(expected, live, "active")

        self.assertIn(
            "Device is not HA standby; rollback is permitted on standby only.",
            failures,
        )
