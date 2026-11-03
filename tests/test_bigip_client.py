from __future__ import annotations

import shlex
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from f5upgrade.bigip_client import BigIPClient  # noqa: E402


class BashCommandQuotingTests(unittest.TestCase):
    command = "ls -1 /shared/images/*.iso 2>/dev/null | sed 's#^.*/##' | sort"

    def test_run_bash_preserves_single_quotes_in_command(self):
        client = BigIPClient("192.0.2.10", "admin", "password")
        client.post = Mock(return_value={})

        client.run_bash(self.command)

        payload = client.post.call_args.args[1]
        self.assertEqual(["-c", self.command], shlex.split(payload["utilCmdArgs"]))

    def test_run_bash_once_preserves_single_quotes_in_command(self):
        client = BigIPClient("192.0.2.10", "admin", "password")
        client.post_once = Mock(return_value={})

        client.run_bash_once(self.command)

        payload = client.post_once.call_args.args[1]
        self.assertEqual(["-c", self.command], shlex.split(payload["utilCmdArgs"]))
