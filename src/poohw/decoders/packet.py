"""Base packet parser for Whoop proprietary BLE packets.

Uses the corrected packet format from jogolden/whoomp:
    [SOF: 0xAA] [LENGTH: 2B LE] [CRC8: 1B] [TYPE] [SEQ] [CMD] [DATA...] [CRC32: 4B LE]
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from poohw.protocol import (
    SOF,
    SOF_SIZE,
    LENGTH_SIZE,
    CRC8_SIZE,
    CRC32_SIZE,
    HEADER_SIZE,
    MIN_PACKET_SIZE,
    PacketType,
    Command,
    crc8,
    crc32,
)


@dataclass
class WhoopPacket:
    """A parsed Whoop proprietary packet."""

    raw: bytes
    packet_type: int | None
    seq: int | None
    command_id: int | None
    payload: bytes
    crc8_valid: bool
    crc32_value: int | None
    crc32_valid: bool | None
    complete: bool

    @property
    def hex(self) -> str:
        return self.raw.hex()

    @property
    def type_name(self) -> str:
        if self.packet_type is None:
            return "?"
        try:
            return PacketType(self.packet_type).name
        except ValueError:
            return f"0x{self.packet_type:02X}"

    @property
    def command_name(self) -> str:
        if self.command_id is None:
            return "?"
        try:
            return Command(self.command_id).name
        except ValueError:
            return f"0x{self.command_id:02X}"

    def __repr__(self) -> str:
        crc = ""
        if self.crc32_value is not None:
            valid = "OK" if self.crc32_valid else "BAD"
            crc = f", crc32={valid}"
        status = "" if self.complete else ", INCOMPLETE"
        return (
            f"WhoopPacket(type={self.type_name}, seq={self.seq}, "
            f"cmd={self.command_name}, payload={self.payload.hex()}{crc}{status})"
        )


class PacketDecoder:
    """Decode raw bytes into WhoopPacket structures."""

    @staticmethod
    def decode(data: bytes | bytearray) -> WhoopPacket | None:
        """Parse raw bytes into a WhoopPacket.

        Returns None if the data doesn't start with SOF or is too short.
        """
        data = bytes(data)

        if len(data) < MIN_PACKET_SIZE:
            return None
        if data[0] != SOF:
            return None

        length_field = struct.unpack_from("<H", data, 1)[0]
        stored_crc8 = data[3]
        expected_crc8 = crc8(data[1:3])
        crc8_valid = stored_crc8 == expected_crc8

        inner_size = length_field - CRC32_SIZE
        if inner_size < 0:
            return None

        inner_start = HEADER_SIZE  # 4
        inner_end = inner_start + inner_size
        total_end = inner_start + length_field

        complete = len(data) >= total_end
        inner = data[inner_start:inner_end] if len(data) >= inner_end else data[inner_start:]

        packet_type = inner[0] if len(inner) > 0 else None
        seq = inner[1] if len(inner) > 1 else None
        command_id = inner[2] if len(inner) > 2 else None
        payload = bytes(inner[3:]) if len(inner) > 3 else b""

        crc32_value = None
        crc32_valid = None
        if complete and len(data) >= inner_end + CRC32_SIZE:
            crc32_value = struct.unpack_from("<I", data, inner_end)[0]
            crc32_valid = crc32_value == crc32(inner)

        return WhoopPacket(
            raw=data,
            packet_type=packet_type,
            seq=seq,
            command_id=command_id,
            payload=payload,
            crc8_valid=crc8_valid,
            crc32_value=crc32_value,
            crc32_valid=crc32_valid,
            complete=complete,
        )

    @staticmethod
    def decode_stream(data: bytes | bytearray) -> list[WhoopPacket]:
        """Decode multiple packets from a byte stream."""
        data = bytes(data)
        packets: list[WhoopPacket] = []
        offset = 0

        while offset < len(data):
            idx = data.find(bytes([SOF]), offset)
            if idx == -1:
                break

            remaining = data[idx:]
            if len(remaining) < MIN_PACKET_SIZE:
                break

            length_field = struct.unpack_from("<H", remaining, 1)[0]
            total = HEADER_SIZE + length_field

            packet = PacketDecoder.decode(remaining[:total])
            if packet and packet.complete:
                packets.append(packet)
                offset = idx + total
            else:
                offset = idx + 1

        return packets
