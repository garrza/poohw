"""Whoop BLE protocol constants and packet helpers."""

import struct

# --- Proprietary BLE UUIDs ---
WHOOP_SERVICE_UUID = "61080001-8d6d-82b8-614a-1c8cb0f8dcc6"
CMD_TO_STRAP_UUID = "61080002-8d6d-82b8-614a-1c8cb0f8dcc6"
CMD_FROM_STRAP_UUID = "61080003-8d6d-82b8-614a-1c8cb0f8dcc6"
DATA_FROM_STRAP_UUID = "61080004-8d6d-82b8-614a-1c8cb0f8dcc6"

# --- Standard BLE UUIDs ---
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# --- Packet constants ---
PACKET_HEADER = 0xAA
HEADER_SIZE = 1  # 0xAA
LENGTH_SIZE = 2  # uint16 little-endian
CHECKSUM_SIZE = 4  # uint32

# --- Known commands (hex strings) ---
# Returns recent sensor data
CMD_GET_SENSOR_DATA = "aa0800a8230e16001147c585"


def parse_packet(data: bytes | bytearray) -> dict | None:
    """Parse a Whoop proprietary packet.

    Packet format:
        [0xAA] [length: 2 bytes LE] [command + payload] [checksum: 4 bytes]

    Returns dict with header, length, command_payload, checksum, or None if invalid.
    """
    if len(data) < HEADER_SIZE + LENGTH_SIZE + CHECKSUM_SIZE:
        return None

    if data[0] != PACKET_HEADER:
        return None

    length_field = struct.unpack_from("<H", data, 1)[0]
    # length_field counts bytes before checksum (header + length_field + payload)
    payload_len = length_field - HEADER_SIZE - LENGTH_SIZE
    if payload_len < 0:
        return None

    expected_total = length_field + CHECKSUM_SIZE

    command_payload = data[HEADER_SIZE + LENGTH_SIZE: HEADER_SIZE + LENGTH_SIZE + payload_len]

    checksum_offset = HEADER_SIZE + LENGTH_SIZE + payload_len
    if len(data) >= checksum_offset + CHECKSUM_SIZE:
        checksum = struct.unpack_from("<I", data, checksum_offset)[0]
    else:
        checksum = None

    return {
        "header": data[0],
        "length_field": length_field,
        "payload_length": payload_len,
        "command_payload": bytes(command_payload),
        "checksum": checksum,
        "expected_total_length": expected_total,
        "actual_length": len(data),
        "complete": len(data) >= expected_total,
    }


def build_packet(command_payload: bytes) -> bytes:
    """Build a Whoop packet (without valid checksum).

    NOTE: The checksum algorithm is not yet reversed. This builds the packet
    with a zeroed checksum. For known commands, use the full hex string directly.
    """
    header = bytes([PACKET_HEADER])
    # length_field = header(1) + length_field(2) + payload
    length_field_value = HEADER_SIZE + LENGTH_SIZE + len(command_payload)
    length = struct.pack("<H", length_field_value)
    # Placeholder checksum — will need to be replaced with real checksum
    checksum = b"\x00\x00\x00\x00"
    return header + length + command_payload + checksum


def hex_to_bytes(hex_str: str) -> bytes:
    """Convert a hex string (with or without spaces) to bytes."""
    return bytes.fromhex(hex_str.replace(" ", ""))


def format_packet(data: bytes | bytearray) -> str:
    """Format a packet as a human-readable string with parsed fields."""
    parsed = parse_packet(data)
    if parsed is None:
        return f"[raw] {data.hex()}"

    parts = [
        f"header=0xAA",
        f"len={parsed['payload_length']}",
        f"payload={parsed['command_payload'].hex()}",
    ]
    if parsed["checksum"] is not None:
        parts.append(f"csum=0x{parsed['checksum']:08X}")
    if not parsed["complete"]:
        parts.append("INCOMPLETE")
    return " ".join(parts)
