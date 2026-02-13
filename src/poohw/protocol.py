"""Whoop BLE protocol constants, packet framing, and CRC implementations.

Packet format (from jogolden/whoomp):
    [SOF: 0xAA] [LENGTH: 2B LE] [CRC8: 1B] [TYPE] [SEQ] [CMD] [DATA...] [CRC32: 4B LE]

- SOF: Always 0xAA
- LENGTH: len(TYPE+SEQ+CMD+DATA) + 4 (for CRC32 trailer), little-endian uint16
- CRC8: CRC-8 (poly 0x07) computed over the 2-byte LENGTH field
- TYPE: Packet type (0x23=COMMAND, 0x24=COMMAND_RESPONSE, etc.)
- SEQ: Sequence number (0x00 works fine)
- CMD: Command ID
- DATA: Variable-length payload
- CRC32: Standard CRC-32 (zlib) over TYPE+SEQ+CMD+DATA, little-endian
"""

import struct
import zlib
from enum import IntEnum

# ---------------------------------------------------------------------------
# BLE UUIDs
# ---------------------------------------------------------------------------
WHOOP_SERVICE_UUID = "61080001-8d6d-82b8-614a-1c8cb0f8dcc6"
CMD_TO_STRAP_UUID = "61080002-8d6d-82b8-614a-1c8cb0f8dcc6"
CMD_FROM_STRAP_UUID = "61080003-8d6d-82b8-614a-1c8cb0f8dcc6"
EVENTS_FROM_STRAP_UUID = "61080004-8d6d-82b8-614a-1c8cb0f8dcc6"
DATA_FROM_STRAP_UUID = "61080005-8d6d-82b8-614a-1c8cb0f8dcc6"
MEMFAULT_UUID = "61080007-8d6d-82b8-614a-1c8cb0f8dcc6"

HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

# ---------------------------------------------------------------------------
# Packet framing constants
# ---------------------------------------------------------------------------
SOF = 0xAA
SOF_SIZE = 1
LENGTH_SIZE = 2
CRC8_SIZE = 1
CRC32_SIZE = 4
HEADER_SIZE = SOF_SIZE + LENGTH_SIZE + CRC8_SIZE  # 4 bytes before payload
MIN_PACKET_SIZE = HEADER_SIZE + CRC32_SIZE  # 8 bytes minimum


# ---------------------------------------------------------------------------
# Packet types
# ---------------------------------------------------------------------------
class PacketType(IntEnum):
    COMMAND = 0x23
    COMMAND_RESPONSE = 0x24
    REALTIME_DATA = 0x28
    REALTIME_RAW_DATA = 0x2B
    HISTORICAL_DATA = 0x2F
    EVENT = 0x30
    METADATA = 0x31
    CONSOLE_LOGS = 0x32
    REALTIME_IMU_DATA = 0x33
    HISTORICAL_IMU_DATA = 0x34


# ---------------------------------------------------------------------------
# Command IDs
# ---------------------------------------------------------------------------
class Command(IntEnum):
    LINK_VALID = 0x01
    GET_MAX_PROTOCOL_VERSION = 0x02
    TOGGLE_REALTIME_HR = 0x03
    REPORT_VERSION_INFO = 0x07
    SET_CLOCK = 0x0A
    GET_CLOCK = 0x0B
    TOGGLE_GENERIC_HR_PROFILE = 0x0E
    TOGGLE_R7_DATA_COLLECTION = 0x10
    RUN_HAPTIC_PATTERN_MAVERICK = 0x13
    ABORT_HISTORICAL_TRANSMITS = 0x14
    SEND_HISTORICAL_DATA = 0x16
    HISTORICAL_DATA_RESULT = 0x17
    FORCE_TRIM = 0x19
    GET_BATTERY_LEVEL = 0x1A
    REBOOT_STRAP = 0x1D
    POWER_CYCLE_STRAP = 0x20
    SET_READ_POINTER = 0x21
    GET_DATA_RANGE = 0x22
    GET_HELLO_HARVARD = 0x23
    START_FIRMWARE_LOAD = 0x24
    LOAD_FIRMWARE_DATA = 0x25
    PROCESS_FIRMWARE_IMAGE = 0x26
    SET_LED_DRIVE = 0x27
    GET_LED_DRIVE = 0x28
    SET_TIA_GAIN = 0x29
    GET_TIA_GAIN = 0x2A
    SET_BIAS_OFFSET = 0x2B
    GET_BIAS_OFFSET = 0x2C
    ENTER_BLE_DFU = 0x2D
    SET_DP_TYPE = 0x34
    FORCE_DP_TYPE = 0x35
    SEND_R10_R11_REALTIME = 0x3F
    SET_ALARM_TIME = 0x42
    GET_ALARM_TIME = 0x43
    RUN_ALARM = 0x44
    DISABLE_ALARM = 0x45
    GET_ADVERTISING_NAME_HARVARD = 0x4C
    SET_ADVERTISING_NAME_HARVARD = 0x4D
    RUN_HAPTICS_PATTERN = 0x4F
    GET_ALL_HAPTICS_PATTERN = 0x50
    START_RAW_DATA = 0x51
    STOP_RAW_DATA = 0x52
    VERIFY_FIRMWARE_IMAGE = 0x53
    GET_BODY_LOCATION_AND_STATUS = 0x54
    ENTER_HIGH_FREQ_SYNC = 0x60
    EXIT_HIGH_FREQ_SYNC = 0x61
    GET_EXTENDED_BATTERY_INFO = 0x62
    RESET_FUEL_GAUGE = 0x63
    CALIBRATE_CAPSENSE = 0x64
    TOGGLE_IMU_MODE_HISTORICAL = 0x69
    TOGGLE_IMU_MODE = 0x6A
    ENABLE_OPTICAL_DATA = 0x6B
    TOGGLE_OPTICAL_MODE = 0x6C
    START_DEVICE_CONFIG_KEY_EXCHANGE = 0x73
    SEND_NEXT_DEVICE_CONFIG = 0x74
    START_FF_KEY_EXCHANGE = 0x75
    SEND_NEXT_FF = 0x76
    SET_DEVICE_CONFIG_VALUE = 0x77
    SET_FF_VALUE = 0x78
    GET_DEVICE_CONFIG_VALUE = 0x79
    STOP_HAPTICS = 0x7A
    SELECT_WRIST = 0x7B
    TOGGLE_LABRADOR_DATA_GENERATION = 0x7C
    TOGGLE_LABRADOR_RAW_SAVE = 0x7D
    GET_FF_VALUE = 0x80
    SET_RESEARCH_PACKET = 0x83
    GET_RESEARCH_PACKET = 0x84
    TOGGLE_LABRADOR_FILTERED = 0x8B
    SET_ADVERTISING_NAME = 0x8C
    GET_ADVERTISING_NAME = 0x8D
    START_FIRMWARE_LOAD_NEW = 0x8E
    LOAD_FIRMWARE_DATA_NEW = 0x8F
    PROCESS_FIRMWARE_IMAGE_NEW = 0x90
    GET_HELLO = 0x91


# ---------------------------------------------------------------------------
# Event IDs (received from strap)
# ---------------------------------------------------------------------------
class Event(IntEnum):
    STRAP_DRIVEN_ALARM_SET = 0x38
    STRAP_DRIVEN_ALARM_EXECUTED = 0x39
    APP_DRIVEN_ALARM_EXECUTED = 0x3A
    STRAP_DRIVEN_ALARM_DISABLED = 0x3B
    HAPTICS_FIRED = 0x3C
    HAPTICS_TERMINATED = 0x64


# ---------------------------------------------------------------------------
# CRC implementations
# ---------------------------------------------------------------------------

# CRC-8 lookup table (polynomial 0x07)
_CRC8_TABLE = [
    0x00, 0x07, 0x0E, 0x09, 0x1C, 0x1B, 0x12, 0x15,
    0x38, 0x3F, 0x36, 0x31, 0x24, 0x23, 0x2A, 0x2D,
    0x70, 0x77, 0x7E, 0x79, 0x6C, 0x6B, 0x62, 0x65,
    0x48, 0x4F, 0x46, 0x41, 0x54, 0x53, 0x5A, 0x5D,
    0xE0, 0xE7, 0xEE, 0xE9, 0xFC, 0xFB, 0xF2, 0xF5,
    0xD8, 0xDF, 0xD6, 0xD1, 0xC4, 0xC3, 0xCA, 0xCD,
    0x90, 0x97, 0x9E, 0x99, 0x8C, 0x8B, 0x82, 0x85,
    0xA8, 0xAF, 0xA6, 0xA1, 0xB4, 0xB3, 0xBA, 0xBD,
    0xC7, 0xC0, 0xC9, 0xCE, 0xDB, 0xDC, 0xD5, 0xD2,
    0xFF, 0xF8, 0xF1, 0xF6, 0xE3, 0xE4, 0xED, 0xEA,
    0xB7, 0xB0, 0xB9, 0xBE, 0xAB, 0xAC, 0xA5, 0xA2,
    0x8F, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9D, 0x9A,
    0x27, 0x20, 0x29, 0x2E, 0x3B, 0x3C, 0x35, 0x32,
    0x1F, 0x18, 0x11, 0x16, 0x03, 0x04, 0x0D, 0x0A,
    0x57, 0x50, 0x59, 0x5E, 0x4B, 0x4C, 0x45, 0x42,
    0x6F, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7D, 0x7A,
    0x89, 0x8E, 0x87, 0x80, 0x95, 0x92, 0x9B, 0x9C,
    0xB1, 0xB6, 0xBF, 0xB8, 0xAD, 0xAA, 0xA3, 0xA4,
    0xF9, 0xFE, 0xF7, 0xF0, 0xE5, 0xE2, 0xEB, 0xEC,
    0xC1, 0xC6, 0xCF, 0xC8, 0xDD, 0xDA, 0xD3, 0xD4,
    0x69, 0x6E, 0x67, 0x60, 0x75, 0x72, 0x7B, 0x7C,
    0x51, 0x56, 0x5F, 0x58, 0x4D, 0x4A, 0x43, 0x44,
    0x19, 0x1E, 0x17, 0x10, 0x05, 0x02, 0x0B, 0x0C,
    0x21, 0x26, 0x2F, 0x28, 0x3D, 0x3A, 0x33, 0x34,
    0x4E, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5C, 0x5B,
    0x76, 0x71, 0x78, 0x7F, 0x6A, 0x6D, 0x64, 0x63,
    0x3E, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2C, 0x2B,
    0x06, 0x01, 0x08, 0x0F, 0x1A, 0x1D, 0x14, 0x13,
    0xAE, 0xA9, 0xA0, 0xA7, 0xB2, 0xB5, 0xBC, 0xBB,
    0x96, 0x91, 0x98, 0x9F, 0x8A, 0x8D, 0x84, 0x83,
    0xDE, 0xD9, 0xD0, 0xD7, 0xC2, 0xC5, 0xCC, 0xCB,
    0xE6, 0xE1, 0xE8, 0xEF, 0xFA, 0xFD, 0xF4, 0xF3,
]


def crc8(data: bytes | bytearray) -> int:
    """CRC-8 with polynomial 0x07, computed over the given bytes."""
    crc = 0
    for b in data:
        crc = _CRC8_TABLE[crc ^ b]
    return crc


def crc32(data: bytes | bytearray) -> int:
    """Standard CRC-32 (zlib-compatible)."""
    return zlib.crc32(bytes(data)) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Packet building / parsing
# ---------------------------------------------------------------------------

def build_packet(
    packet_type: int,
    command: int,
    data: bytes = b"",
    seq: int = 0,
) -> bytes:
    """Build a fully framed Whoop packet with valid CRC-8 and CRC-32.

    Args:
        packet_type: Packet type byte (e.g., PacketType.COMMAND = 0x23).
        command: Command ID byte (e.g., Command.RUN_ALARM = 0x44).
        data: Payload data bytes (can be empty).
        seq: Sequence number (default 0).

    Returns:
        Complete framed packet ready to write to CMD_TO_STRAP.
    """
    inner = bytes([packet_type, seq, command]) + data
    length = len(inner) + CRC32_SIZE
    length_bytes = struct.pack("<H", length)
    header_crc = crc8(length_bytes)
    payload_crc = struct.pack("<I", crc32(inner))
    return bytes([SOF]) + length_bytes + bytes([header_crc]) + inner + payload_crc


def parse_packet(data: bytes | bytearray) -> dict | None:
    """Parse a framed Whoop packet.

    Returns dict with all fields, or None if too short / bad SOF.
    """
    data = bytes(data)
    if len(data) < MIN_PACKET_SIZE:
        return None
    if data[0] != SOF:
        return None

    length_field = struct.unpack_from("<H", data, 1)[0]
    header_crc = data[3]
    expected_crc8 = crc8(data[1:3])

    inner_start = HEADER_SIZE  # 4
    inner_size = length_field - CRC32_SIZE
    if inner_size < 0:
        return None
    inner_end = inner_start + inner_size
    crc32_end = inner_start + length_field

    complete = len(data) >= crc32_end
    inner = data[inner_start:inner_end] if len(data) >= inner_end else data[inner_start:]

    packet_type = inner[0] if len(inner) > 0 else None
    seq = inner[1] if len(inner) > 1 else None
    cmd = inner[2] if len(inner) > 2 else None
    payload = inner[3:] if len(inner) > 3 else b""

    stored_crc32 = None
    crc32_valid = None
    if complete:
        stored_crc32 = struct.unpack_from("<I", data, inner_end)[0]
        crc32_valid = stored_crc32 == crc32(inner)

    return {
        "raw": data,
        "length_field": length_field,
        "header_crc8": header_crc,
        "header_crc8_valid": header_crc == expected_crc8,
        "packet_type": packet_type,
        "seq": seq,
        "command": cmd,
        "payload": bytes(payload),
        "crc32": stored_crc32,
        "crc32_valid": crc32_valid,
        "complete": complete,
    }


def format_packet(data: bytes | bytearray) -> str:
    """Format a packet as a human-readable string."""
    p = parse_packet(data)
    if p is None:
        return f"[raw] {bytes(data).hex()}"

    type_name = ""
    try:
        type_name = f" ({PacketType(p['packet_type']).name})"
    except (ValueError, TypeError):
        pass

    cmd_name = ""
    if p["command"] is not None:
        try:
            cmd_name = f" ({Command(p['command']).name})"
        except ValueError:
            pass

    parts = [f"type=0x{p['packet_type']:02X}{type_name}"]
    if p["seq"] is not None:
        parts.append(f"seq={p['seq']}")
    if p["command"] is not None:
        parts.append(f"cmd=0x{p['command']:02X}{cmd_name}")
    if p["payload"]:
        parts.append(f"data={p['payload'].hex()}")
    if p["crc32"] is not None:
        valid = "OK" if p["crc32_valid"] else "BAD"
        parts.append(f"crc32=0x{p['crc32']:08X}({valid})")
    if not p["header_crc8_valid"]:
        parts.append("crc8=BAD")
    if not p["complete"]:
        parts.append("INCOMPLETE")
    return " ".join(parts)


def hex_to_bytes(hex_str: str) -> bytes:
    """Convert a hex string (with or without spaces) to bytes."""
    return bytes.fromhex(hex_str.replace(" ", ""))
