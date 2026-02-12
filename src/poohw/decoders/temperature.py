"""Skin temperature decoder for Whoop proprietary packets."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from poohw.decoders.packet import WhoopPacket

# Suspected command IDs for temperature data
TEMP_COMMAND_IDS = {0x40, 0x41}


@dataclass
class TemperatureData:
    """Decoded temperature data from a proprietary packet."""

    skin_temp_c: float
    skin_temp_f: float
    raw_value: int
    raw_payload: bytes = b""

    def __repr__(self) -> str:
        return f"Temperature(skin={self.skin_temp_c:.2f}C / {self.skin_temp_f:.2f}F)"


class TemperatureDecoder:
    """Decode skin temperature from Whoop proprietary packets.

    The Whoop 4.0 has a skin temperature sensor. Temperature is likely
    encoded as a scaled integer (e.g., uint16 in hundredths of a degree C,
    or int16 with scale factor).

    NOTE: Exact encoding needs validation against captures.
    Strategy: Try common encodings and validate against expected skin temp range (30-40 C).
    """

    @staticmethod
    def can_decode(packet: WhoopPacket) -> bool:
        """Check if this packet likely contains temperature data."""
        return packet.command_id in TEMP_COMMAND_IDS

    @staticmethod
    def decode(packet: WhoopPacket) -> TemperatureData | None:
        """Decode temperature from a proprietary packet."""
        payload = packet.payload
        if len(payload) < 3:
            return None

        # Try uint16 LE at offset 1 (after command byte), as hundredths of C
        raw = struct.unpack_from("<H", payload, 1)[0]
        temp_c = raw / 100.0
        if 25.0 <= temp_c <= 45.0:
            return TemperatureData(
                skin_temp_c=round(temp_c, 2),
                skin_temp_f=round(temp_c * 9.0 / 5.0 + 32.0, 2),
                raw_value=raw,
                raw_payload=payload,
            )

        # Try int16 LE at offset 1, as tenths of C
        raw_signed = struct.unpack_from("<h", payload, 1)[0]
        temp_c = raw_signed / 10.0
        if 25.0 <= temp_c <= 45.0:
            return TemperatureData(
                skin_temp_c=round(temp_c, 2),
                skin_temp_f=round(temp_c * 9.0 / 5.0 + 32.0, 2),
                raw_value=raw_signed,
                raw_payload=payload,
            )

        # Try raw as direct Celsius (uint8 at offset 1)
        raw_byte = payload[1]
        if 25 <= raw_byte <= 45:
            return TemperatureData(
                skin_temp_c=float(raw_byte),
                skin_temp_f=round(raw_byte * 9.0 / 5.0 + 32.0, 2),
                raw_value=raw_byte,
                raw_payload=payload,
            )

        return None
