from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from f5upgrade.ha import resolve_active_peer_and_sync_group  # noqa: E402


def device(name: str, address: str, state: str, self_device: bool = False):
    return {
        "name": name,
        "hostname": name,
        "managementIp": address,
        "failoverState": state,
        "selfDevice": self_device,
    }


class AutoSyncSelectionTests(unittest.TestCase):
    def client_with_groups(self, groups):
        client = Mock()
        client.base_url = "https://10.0.0.2"
        client.devices.return_value = {
            "items": [
                device("active.example.test", "10.0.0.1", "active"),
                device(
                    "standby.example.test",
                    "10.0.0.2",
                    "standby",
                    self_device=True,
                ),
            ]
        }
        client.get.return_value = {"items": groups}
        return client

    def test_selects_non_hidden_sync_failover_group(self):
        members = [
            "/Common/active.example.test",
            "/Common/standby.example.test",
        ]
        client = self.client_with_groups(
            [
                {
                    "name": "application-device-group",
                    "type": "sync-failover",
                    "autoSync": "enabled",
                    "devices": members,
                },
                {
                    "name": "device_trust_group",
                    "type": "sync-failover",
                    "hidden": "true",
                    "devices": members,
                },
                {
                    "name": "system-datasync-group",
                    "hidden": "true",
                    "devices": members,
                },
            ]
        )

        active_host, group = resolve_active_peer_and_sync_group(client)

        self.assertEqual("10.0.0.1", active_host)
        self.assertEqual("application-device-group", group)

    def test_blocks_when_multiple_sync_failover_groups_match(self):
        members = [
            "/Common/active.example.test",
            "/Common/standby.example.test",
        ]
        client = self.client_with_groups(
            [
                {"name": "first", "type": "sync-failover", "devices": members},
                {"name": "second", "type": "sync-failover", "devices": members},
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            resolve_active_peer_and_sync_group(client)

    def test_blocks_when_no_sync_failover_group_matches(self):
        client = self.client_with_groups(
            [{"name": "system-group", "hidden": "false", "devices": []}]
        )

        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            resolve_active_peer_and_sync_group(client)

    def test_reads_membership_with_tmsh_when_group_response_omits_devices(self):
        client = self.client_with_groups(
            [
                {
                    "name": "failover",
                    "type": "sync-failover",
                    "autoSync": "enabled",
                }
            ]
        )
        client.run_bash.return_value = {
            "commandResult": (
                "cm device-group failover {\n"
                "    devices {\n"
                "        active.example.test\n"
                "        standby.example.test\n"
                "    }\n"
                "}\n"
            )
        }

        active_host, group = resolve_active_peer_and_sync_group(client)

        self.assertEqual("10.0.0.1", active_host)
        self.assertEqual("failover", group)
        client.run_bash.assert_called_once_with(
            "tmsh -q list cm device-group failover devices",
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
