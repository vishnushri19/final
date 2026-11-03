from __future__ import annotations

import ipaddress
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from .bigip_client import BigIPClient


def _short_hostname(value: object) -> str:
    """Return a case-insensitive hostname label without domain or route suffix."""
    return str(value or "").strip().lower().rstrip(".").split("/", 1)[0].split(".", 1)[0]


def _ip_address(value: object) -> Optional[str]:
    """Normalize a BIG-IP management address, which may include a route suffix."""
    candidate = str(value or "").strip().split("/", 1)[0].split("%", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _connection_addresses(host: str) -> set[str]:
    direct_address = _ip_address(host)
    if direct_address:
        return {direct_address}

    try:
        return {
            _ip_address(info[4][0])
            for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            if _ip_address(info[4][0])
        }
    except OSError:
        return set()


def discover_devices(client: BigIPClient) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Discover devices in the BIG-IP trust domain.

    Returns:
      - local_device_name (best-effort)
      - devices list (raw device objects from /mgmt/tm/cm/device)

    Notes:
      - Different BIG-IP versions expose slightly different fields.
      - V1 uses safe heuristics without assuming a fixed schema.
    """
    payload = client.devices()
    devices = payload.get("items", []) if isinstance(payload, dict) else []

    local_name: Optional[str] = None

    # Heuristic 1: explicit self flag (seen on some builds)
    self_devices = [d for d in devices if d.get("selfDevice") is True]
    if len(self_devices) == 1:
        local_name = self_devices[0].get("name")

    connected_host = urlsplit(client.base_url).hostname or ""
    connected_name = _short_hostname(connected_host)

    # Heuristic 2: match the supplied hostname to the device name or hostname.
    # This supports a short hostname when BIG-IP inventory uses an FQDN.
    if local_name is None:
        hostname_matches = [
            d
            for d in devices
            if connected_name
            and connected_name
            in {
                _short_hostname(d.get("name")),
                _short_hostname(d.get("hostname")),
            }
        ]
        if len(hostname_matches) == 1:
            local_name = hostname_matches[0].get("name")

    # Heuristic 3: match the literal or DNS-resolved connection address to the
    # management address. Do not select a device if DNS produces an ambiguity.
    if local_name is None:
        connected_addresses = _connection_addresses(connected_host)
        address_matches = [
            d
            for d in devices
            if _ip_address(d.get("managementIp") or d.get("managementAddress"))
            in connected_addresses
        ]
        if len(address_matches) == 1:
            local_name = address_matches[0].get("name")

    return local_name, devices


def summarize_devices(devices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Produce a compact, safe summary of devices for reporting.
    """
    summary: List[Dict[str, Any]] = []
    for d in devices:
        summary.append(
            {
                "name": d.get("name"),
                "hostname": d.get("hostname"),
                "managementIp": d.get("managementIp") or d.get("managementAddress"),
                "failoverState": d.get("failoverState"),
                "version": d.get("version"),
            }
        )
    return summary
