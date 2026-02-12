"""Blood oxygen (SpO2) decoder for Whoop proprietary packets."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from poohw.decoders.packet import WhoopPacket

# Suspected command IDs for SpO2 data
SPO2_COMMAND_IDS = {0x50, 0x51}


@dataclass
class SpO2Data:
    """Decoded SpO2 data from a proprietary packet."""

    spo2_percent: float
    confidence: int | None = None
    raw_value: int = 0
    raw_payload: bytes = b""

    def __repr__(self) -> str:
        conf = f", confidence={self.confidence}%" if self.confidence is not None else ""
        return f"SpO2({self.spo2_percent:.1f}%{conf})"


class SpO2Decoder:
    """Decode blood oxygen data from Whoop proprietary packets.

    SpO2 is typically 90-100% for healthy individuals. The value is
    likely encoded as a uint8 percentage or a scaled uint16.

    NOTE: Exact encoding needs validation against captures.
    """

    @staticmethod
    def can_decode(packet: WhoopPacket) -> bool:
        """Check if this packet likely contains SpO2 data."""
        return packet.command_id in SPO2_COMMAND_IDS

    @staticmethod
    def decode(packet: WhoopPacket) -> SpO2Data | None:
        """Decode SpO2 from a proprietary packet."""
        payload = packet.payload
        if len(payload) < 2:
            return None

        # Try uint8 at offset 1 — direct percentage
        raw_byte = payload[1]
        if 70 <= raw_byte <= 100:
            confidence = None
            if len(payload) >= 3:
                conf = payload[2]
                if 0 <= conf <= 100:
                    confidence = conf
            return SpO2Data(
                spo2_percent=float(raw_byte),
                confidence=confidence,
                raw_value=raw_byte,
                raw_payload=payload,
            )

        # Try uint16 LE at offset 1, as tenths of a percent
        if len(payload) >= 3:
            raw16 = struct.unpack_from("<H", payload, 1)[0]
            spo2 = raw16 / 10.0
            if 70.0 <= spo2 <= 100.0:
                confidence = None
                if len(payload) >= 4:
                    conf = payload[3]
                    if 0 <= conf <= 100:
                        confidence = conf
                return SpO2Data(
                    spo2_percent=round(spo2, 1),
                    confidence=confidence,
                    raw_value=raw16,
                    raw_payload=payload,
                )

        return None
