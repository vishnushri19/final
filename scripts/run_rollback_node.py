from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from f5upgrade.bigip_client import BigIPClient
from f5upgrade.config import load_settings
from f5upgrade.execution import exec_reboot_to_volume_standby, exec_wait_postboot
from f5upgrade.ha import get_failover_role
from f5upgrade.report import CheckResult, to_report, write_json, write_markdown
from f5upgrade.rollback import (
    VolumeEvidence,
    live_volume_inventory,
    pre_upgrade_volume_from_report,
    validate_rollback_candidate,
)


def _safe_host(host: str) -> str:
    return host.replace(":", "_").replace("/", "_").replace(".", "_")


def _approved() -> bool:
    return os.getenv("ROLLBACK_APPROVED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _precheck_report_path(output_dir: Path, safe_host: str) -> Path:
    configured = os.getenv("ROLLBACK_PRECHECK_REPORT", "").strip()
    if configured:
        return Path(configured)
    return output_dir / f"upgrade_flow_report_{safe_host}.json"


def _read_pre_upgrade_volume(path: Path) -> VolumeEvidence:
    with path.open(encoding="utf-8") as file_handle:
        payload = json.load(file_handle)
    if not isinstance(payload, dict):
        raise ValueError("Pre-upgrade report must contain a JSON object.")
    return pre_upgrade_volume_from_report(payload)


def _live_inventory(client: BigIPClient) -> list[VolumeEvidence]:
    return live_volume_inventory(client.software_volumes())


def _validation_result(
    *,
    expected: VolumeEvidence,
    live: list[VolumeEvidence],
    role: str | None,
    stage: str,
) -> CheckResult:
    failures = validate_rollback_candidate(expected, live, role)
    return CheckResult(
        id=f"RB-{stage}-001",
        category="Rollback",
        name=f"Rollback candidate validation ({stage.lower()})",
        status="PASS" if not failures else "FAIL",
        details={
            "expected_pre_upgrade_volume": expected.to_dict(),
            "live_volumes": [volume.to_dict() for volume in live],
            "role": role,
            "failures": failures,
        },
    )


def _write_report(
    output_dir: Path,
    safe_host: str,
    host: str,
    precheck_report: Path,
    results: list[CheckResult],
) -> None:
    report = to_report(
        results,
        meta={
            "bigip_host": host,
            "mode": "rollback",
            "precheck_report": str(precheck_report),
            "auto_sync": "unchanged",
        },
    )
    json_path = output_dir / f"rollback_report_{safe_host}.json"
    markdown_path = output_dir / f"rollback_report_{safe_host}.md"
    write_json(str(json_path), report)
    write_markdown(str(markdown_path), report)
    print(f"[+] Wrote rollback report: {markdown_path}")


def main() -> int:
    """Reboot a standby device into its verified pre-upgrade volume."""
    settings = load_settings()
    safe_host = _safe_host(settings.host)
    output_dir = Path("outputs") / settings.crq_number
    output_dir.mkdir(parents=True, exist_ok=True)
    precheck_report = _precheck_report_path(output_dir, safe_host)
    results: list[CheckResult] = []

    if not _approved():
        results.append(
            CheckResult(
                id="RB-APPROVAL-001",
                category="Rollback",
                name="Explicit rollback approval",
                status="FAIL",
                details={
                    "error": (
                        "Set ROLLBACK_APPROVED=true to authorize this "
                        "separate rollback command."
                    )
                },
            )
        )
        _write_report(
            output_dir, safe_host, settings.host, precheck_report, results
        )
        return 2

    try:
        expected = _read_pre_upgrade_volume(precheck_report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        results.append(
            CheckResult(
                id="RB-EVIDENCE-001",
                category="Rollback",
                name="Pre-upgrade rollback evidence",
                status="FAIL",
                details={
                    "precheck_report": str(precheck_report),
                    "error": str(exc),
                },
            )
        )
        _write_report(
            output_dir, safe_host, settings.host, precheck_report, results
        )
        return 2

    client = BigIPClient(
        host=settings.host,
        username=settings.username,
        password=settings.password,
        verify_tls=settings.verify_tls,
        timeout=settings.timeout,
    )

    try:
        first_live = _live_inventory(client)
        first_role = get_failover_role(client)
        first_validation = _validation_result(
            expected=expected,
            live=first_live,
            role=first_role,
            stage="LIVE",
        )
    except Exception as exc:
        first_validation = CheckResult(
            id="RB-LIVE-001",
            category="Rollback",
            name="Rollback candidate validation (live)",
            status="FAIL",
            details={"error": str(exc)},
        )
    results.append(first_validation)
    if first_validation.status != "PASS":
        _write_report(
            output_dir, safe_host, settings.host, precheck_report, results
        )
        return 2

    try:
        final_live = _live_inventory(client)
        final_role = get_failover_role(client)
        final_validation = _validation_result(
            expected=expected,
            live=final_live,
            role=final_role,
            stage="FINAL",
        )
    except Exception as exc:
        final_validation = CheckResult(
            id="RB-FINAL-001",
            category="Rollback",
            name="Rollback candidate validation (final)",
            status="FAIL",
            details={"error": str(exc)},
        )
    results.append(final_validation)
    if final_validation.status != "PASS":
        _write_report(
            output_dir, safe_host, settings.host, precheck_report, results
        )
        return 2

    reboot = exec_reboot_to_volume_standby(client, expected.volume)
    results.append(reboot)
    if reboot.status == "PASS":
        results.append(
            exec_wait_postboot(
                client,
                expected.version,
                allow_standalone=False,
            )
        )

    _write_report(output_dir, safe_host, settings.host, precheck_report, results)
    report = to_report(results, meta={"bigip_host": settings.host})
    return 0 if report["overall_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
