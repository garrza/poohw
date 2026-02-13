"""Shared fixtures and helpers for the poohw test suite."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from poohw.protocol import (
    PacketType,
    Command,
    HistoricalRecordType,
    build_packet,
)
from poohw.decoders.packet import PacketDecoder, WhoopPacket


# ---------------------------------------------------------------------------
# Packet-building helpers
# ---------------------------------------------------------------------------


def make_packet(
    packet_type: int = PacketType.COMMAND,
    command: int = Command.GET_BATTERY_LEVEL,
    data: bytes = b"",
    seq: int = 0,
) -> WhoopPacket:
    """Build a Whoop packet and return the decoded WhoopPacket."""
    raw = build_packet(packet_type, command, data, seq)
    wp = PacketDecoder.decode(raw)
    assert wp is not None, f"Failed to decode built packet: {raw.hex()}"
    return wp


def make_realtime_packet(
    command: int = 0x00,
    data: bytes = b"",
    seq: int = 0,
) -> WhoopPacket:
    """Build a REALTIME_DATA (0x28) packet."""
    return make_packet(PacketType.REALTIME_DATA, command, data, seq)


def make_realtime_raw_packet(
    command: int = 0x00,
    data: bytes = b"",
) -> WhoopPacket:
    """Build a REALTIME_RAW_DATA (0x2B) packet."""
    return make_packet(PacketType.REALTIME_RAW_DATA, command, data)


def make_imu_packet(
    command: int = 0x00,
    data: bytes = b"",
) -> WhoopPacket:
    """Build a REALTIME_IMU_DATA (0x33) packet."""
    return make_packet(PacketType.REALTIME_IMU_DATA, command, data)


def make_historical_imu_packet(
    command: int = 0x00,
    data: bytes = b"",
) -> WhoopPacket:
    """Build a HISTORICAL_IMU_DATA (0x34) packet."""
    return make_packet(PacketType.HISTORICAL_IMU_DATA, command, data)


def make_historical_packet(
    record_subtype: int = HistoricalRecordType.COMPREHENSIVE,
    data: bytes = b"",
) -> WhoopPacket:
    """Build a HISTORICAL_DATA (0x2F) packet with the given subtype."""
    return make_packet(PacketType.HISTORICAL_DATA, record_subtype, data)


def make_command_packet(
    command: int = Command.GET_BATTERY_LEVEL,
    data: bytes = b"",
    seq: int = 0,
) -> WhoopPacket:
    """Build a COMMAND (0x23) packet."""
    return make_packet(PacketType.COMMAND, command, data, seq)


def make_comprehensive_payload(
    timestamp: int = 1707840000,
    hr_bpm: int = 72,
    rr_intervals: list[int] | None = None,
    temp_c: float = 36.50,
    ac_red: int = 500,
    dc_red: int = 10000,
    ac_ir: int = 1000,
    dc_ir: int = 10000,
    pad_to: int = 92,
) -> bytes:
    """Build a synthetic 0x5C comprehensive record payload.

    Default values produce:
    - HR 72 bpm with 4 RR intervals
    - Temperature 36.50 C
    - SpO2 R = 0.5 -> ~97.5%
    """
    if rr_intervals is None:
        rr_intervals = [830, 820, 840, 825]
    rr_count = len(rr_intervals)

    buf = bytearray()
    buf += struct.pack("<I", timestamp)     # [0:4]
    buf.append(hr_bpm)                      # [4]
    buf.append(rr_count)                    # [5]
    for rr in rr_intervals:
        buf += struct.pack("<H", rr)        # [6:6+2N]

    # Pad to offset 22 for temperature field
    while len(buf) < 22:
        buf.append(0x00)

    # Temperature: encode as LE uint32 / 100_000 → °C, padded to 12 bytes
    temp_raw = int(temp_c * 100_000)
    buf += struct.pack("<I", temp_raw) + b"\x00" * 8   # [22:34]

    # SpO2 raw section: 4 uint32 values simulating AC/DC readings
    buf += struct.pack("<IIII", ac_red, dc_red, ac_ir, dc_ir)  # [34:50]

    # Pad to desired total size
    while len(buf) < pad_to:
        buf.append(0x00)

    return bytes(buf)


# ---------------------------------------------------------------------------
# JSONL capture file helpers
# ---------------------------------------------------------------------------


def write_jsonl(path: Path, entries: list[dict]) -> Path:
    """Write a list of dicts as JSONL to the given path."""
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return path


def make_capture_entry(
    uuid: str,
    hex_data: str,
    timestamp: str = "2024-02-13T12:00:00Z",
) -> dict:
    """Create a single JSONL capture entry."""
    return {
        "uuid": uuid,
        "hex_data": hex_data,
        "timestamp": timestamp,
    }
