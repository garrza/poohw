"""Shared BLE helpers for connecting to and interacting with Whoop devices.

These utilities are used across streaming, capture, and command modules to
avoid duplicating the same service-discovery logic.
"""

from __future__ import annotations

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from poohw.protocol import char_role, is_proprietary_uuid


def find_write_char(client: BleakClient) -> str | None:
    """Find the CMD_TO_STRAP writable characteristic on the proprietary service.

    Returns the UUID string, or None if not found.
    """
    for service in client.services:
        if is_proprietary_uuid(service.uuid):
            for char in service.characteristics:
                if "write" in char.properties or "write-without-response" in char.properties:
                    return char.uuid
    return None


def find_notify_chars(client: BleakClient) -> list[tuple[str, str]]:
    """Find all notify-capable characteristics on the proprietary service.

    Returns a list of (uuid, friendly_name) tuples.
    """
    result: list[tuple[str, str]] = []
    for service in client.services:
        if is_proprietary_uuid(service.uuid):
            for char in service.characteristics:
                if "notify" in char.properties:
                    name = char_role(char.uuid) or char.uuid[:12] + "..."
                    result.append((char.uuid, name))
    return result


def dump_services(client: BleakClient) -> None:
    """Print all discovered services and characteristics."""
    print("\n  Available services/characteristics:")
    for service in client.services:
        print(f"    Service: {service.uuid} [{service.description}]")
        for char in service.characteristics:
            props = ", ".join(sorted(char.properties))
            role = char_role(char.uuid)
            tag = f" <-- {role}" if role else ""
            print(f"      {char.uuid} [{props}]{tag}")
