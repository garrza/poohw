"""Base packet parser for Whoop proprietary BLE packets."""

from __future__ import annotations

import struct
from dataclasses import dataclass

PACKET_HEADER = 0xAA


@dataclass
class WhoopPacket:
    """A parsed Whoop proprietary packet."""

    raw: bytes
    header: int
    payload_length: int
    command_id: int | None
    payload: bytes
    checksum: int | None
    complete: bool

    @property
    def hex(self) -> str:
        return self.raw.hex()

    def __repr__(self) -> str:
        cmd = f"0x{self.command_id:02X}" if self.command_id is not None else "?"
        csum = f"0x{self.checksum:08X}" if self.checksum is not None else "?"
        status = "" if self.complete else " INCOMPLETE"
        return (
            f"WhoopPacket(cmd={cmd}, payload_len={self.payload_length}, "
            f"payload={self.payload.hex()}, checksum={csum}{status})"
        )


class PacketDecoder:
    """Decode raw bytes into WhoopPacket structures."""

    HEADER_SIZE = 1
    LENGTH_SIZE = 2
    CHECKSUM_SIZE = 4
    MIN_PACKET_SIZE = HEADER_SIZE + LENGTH_SIZE + CHECKSUM_SIZE  # 7 bytes

    @staticmethod
    def decode(data: bytes | bytearray) -> WhoopPacket | None:
        """Parse raw bytes into a WhoopPacket.

        The length field appears to count all bytes before the checksum
        (i.e., header + length_field + payload), so:
            payload_size = length_field_value - HEADER_SIZE - LENGTH_SIZE
            total_packet  = length_field_value + CHECKSUM_SIZE

        Returns None if the data doesn't start with the expected header
        or is too short to contain even a minimal packet.
        """
        data = bytes(data)

        if len(data) < PacketDecoder.MIN_PACKET_SIZE:
            return None

        if data[0] != PACKET_HEADER:
            return None

        length_field = struct.unpack_from("<H", data, 1)[0]

        # length_field = bytes before checksum (header + len_field + payload)
        payload_size = length_field - PacketDecoder.HEADER_SIZE - PacketDecoder.LENGTH_SIZE
        if payload_size < 0:
            return None

        payload_start = PacketDecoder.HEADER_SIZE + PacketDecoder.LENGTH_SIZE
        payload_end = payload_start + payload_size
        checksum_end = payload_end + PacketDecoder.CHECKSUM_SIZE

        complete = len(data) >= checksum_end

        # Extract payload (may be truncated if packet is incomplete)
        payload = data[payload_start:payload_end]

        # Extract command ID (first byte of payload, if available)
        command_id = payload[0] if len(payload) > 0 else None

        # Extract checksum if complete
        checksum = None
        if complete:
            checksum = struct.unpack_from("<I", data, payload_end)[0]

        return WhoopPacket(
            raw=data,
            header=data[0],
            payload_length=payload_size,
            command_id=command_id,
            payload=payload,
            checksum=checksum,
            complete=complete,
        )

    @staticmethod
    def decode_stream(data: bytes | bytearray) -> list[WhoopPacket]:
        """Decode multiple packets from a byte stream.

        Scans for 0xAA headers and attempts to parse each packet.
        Useful for processing concatenated or buffered data.
        """
        data = bytes(data)
        packets: list[WhoopPacket] = []
        offset = 0

        while offset < len(data):
            # Find next header
            idx = data.find(bytes([PACKET_HEADER]), offset)
            if idx == -1:
                break

            remaining = data[idx:]
            packet = PacketDecoder.decode(remaining)
            if packet and packet.complete:
                packets.append(packet)
                # Total size = header + length_field + payload + checksum
                total = PacketDecoder.HEADER_SIZE + PacketDecoder.LENGTH_SIZE + packet.payload_length + PacketDecoder.CHECKSUM_SIZE
                offset = idx + total
            else:
                # Try next byte
                offset = idx + 1

        return packets
