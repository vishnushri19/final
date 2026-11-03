from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class VolumeEvidence:
    volume: str
    version: str
    build: str
    status: str
    active: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_active(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "active", "1"}


def _volumes_from_payload(payload: Any) -> list[VolumeEvidence]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []

    volumes: list[VolumeEvidence] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        volume = str(item.get("name") or item.get("fullPath") or "").strip()
        if not volume:
            continue
        volumes.append(
            VolumeEvidence(
                volume=volume,
                version=str(item.get("version", "")).strip(),
                build=str(item.get("build", "")).strip(),
                status=str(item.get("status", "")).strip(),
                active=_is_active(item.get("active", False)),
            )
        )
    return volumes


def pre_upgrade_volume_from_report(report: Dict[str, Any]) -> VolumeEvidence:
    """Return the single active, completed volume saved by precheck RB-001."""
    results = report.get("results")
    if not isinstance(results, list):
        raise ValueError("Pre-upgrade report has no results list.")

    rollback_results = [
        result
        for result in results
        if isinstance(result, dict) and result.get("id") == "RB-001"
    ]
    if len(rollback_results) != 1:
        raise ValueError(
            "Expected exactly one RB-001 rollback-readiness result in the "
            "pre-upgrade report."
        )

    details = rollback_results[0].get("details")
    payload = details.get("software_volumes") if isinstance(details, dict) else None
    volumes = _volumes_from_payload(payload)
    candidates = [
        volume
        for volume in volumes
        if volume.active and volume.status.lower() == "complete"
    ]
    if len(candidates) != 1:
        raise ValueError(
            "Expected exactly one active, completed pre-upgrade software "
            f"volume; found {[candidate.volume for candidate in candidates]}."
        )
    return candidates[0]


def live_volume_inventory(payload: Dict[str, Any]) -> list[VolumeEvidence]:
    """Parse a structured live software-volume REST response."""
    volumes = _volumes_from_payload(payload)
    if not volumes:
        raise ValueError(
            "Live software-volume inventory was not a structured REST "
            "response with one or more items."
        )
    return volumes


def validate_rollback_candidate(
    expected: VolumeEvidence,
    live_volumes: Iterable[VolumeEvidence],
    role: Optional[str],
) -> list[str]:
    """Return safety failures that must block a rollback reboot."""
    failures: list[str] = []
    normalized_role = (role or "").strip().lower()
    volumes = list(live_volumes)

    if normalized_role != "standby":
        failures.append(
            "Device is not HA standby; rollback is permitted on standby only."
        )

    active_volumes = [volume for volume in volumes if volume.active]
    if len(active_volumes) != 1:
        failures.append(
            "Live inventory must identify exactly one active software volume; "
            f"found {[volume.volume for volume in active_volumes]}."
        )

    in_progress = [
        volume.volume
        for volume in volumes
        if any(
            state in volume.status.lower()
            for state in (
                "installing",
                "testing",
                "copying",
                "pending",
                "waiting",
                "validating",
            )
        )
    ]
    if in_progress:
        failures.append(
            "Installation is still in progress on volume(s): "
            f"{', '.join(in_progress)}."
        )

    matching = [
        volume for volume in volumes if volume.volume == expected.volume
    ]
    if len(matching) != 1:
        failures.append(
            f"Pre-upgrade volume {expected.volume} is not uniquely present "
            "in the live inventory."
        )
        return failures

    candidate = matching[0]
    if candidate.active:
        failures.append(
            f"Pre-upgrade volume {expected.volume} is already active; "
            "refusing to reboot into the current volume."
        )
    if candidate.status.lower() != "complete":
        failures.append(
            f"Pre-upgrade volume {expected.volume} is not complete "
            f"(status: {candidate.status or 'unknown'})."
        )
    if candidate.version != expected.version or candidate.build != expected.build:
        failures.append(
            f"Pre-upgrade volume {expected.volume} no longer matches saved "
            "version/build evidence."
        )

    return failures
