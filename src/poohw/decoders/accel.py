"""Accelerometer data decoder for Whoop proprietary packets."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from poohw.decoders.packet import WhoopPacket

# Suspected command IDs for accelerometer data
ACCEL_COMMAND_IDS = {0x30, 0x31, 0x32}


@dataclass
class AccelSample:
    """A single accelerometer reading."""

    x: float  # g
    y: float  # g
    z: float  # g

    @property
    def magnitude(self) -> float:
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5

    def __repr__(self) -> str:
        return f"Accel(x={self.x:.3f}g, y={self.y:.3f}g, z={self.z:.3f}g, mag={self.magnitude:.3f}g)"


@dataclass
class AccelData:
    """Decoded accelerometer data from a proprietary packet."""

    samples: list[AccelSample]
    sample_rate_hz: int | None = None
    raw_payload: bytes = b""

    def __repr__(self) -> str:
        return f"AccelData({len(self.samples)} samples)"


class AccelDecoder:
    """Decode accelerometer data from Whoop proprietary packets.

    The Whoop 4.0 has a 3-axis accelerometer. Data is likely sent as
    packed int16 LE samples with a scaling factor to convert to g.

    NOTE: Byte layout is hypothesized and needs validation against captures.
    Common accelerometer encoding: int16 per axis, scale factor ~1/2048 or ~1/4096
    to convert to g units.
    """

    # Typical scale factors for MEMS accelerometers
    # Try common ones; refine once we have correlated data
    SCALE_FACTOR = 1.0 / 2048.0  # int16 → g (±16g range)
    SAMPLE_SIZE = 6  # 3 axes × 2 bytes each

    @staticmethod
    def can_decode(packet: WhoopPacket) -> bool:
        """Check if this packet likely contains accelerometer data."""
        if packet.command_id in ACCEL_COMMAND_IDS:
            return True
        # Heuristic: large payloads with size divisible by 6 (after cmd byte)
        # are likely accel data
        data_len = len(packet.payload) - 1  # minus command ID byte
        if data_len >= 12 and data_len % AccelDecoder.SAMPLE_SIZE == 0:
            return True
        return False

    @staticmethod
    def decode(packet: WhoopPacket, scale: float | None = None) -> AccelData | None:
        """Decode accelerometer samples from a proprietary packet.

        Args:
            packet: The parsed WhoopPacket.
            scale: Override scale factor (int16 raw value * scale = g).
        """
        payload = packet.payload
        if len(payload) < 1 + AccelDecoder.SAMPLE_SIZE:
            return None

        if scale is None:
            scale = AccelDecoder.SCALE_FACTOR

        # Skip command ID byte
        data = payload[1:]
        samples: list[AccelSample] = []

        offset = 0
        while offset + AccelDecoder.SAMPLE_SIZE <= len(data):
            x_raw, y_raw, z_raw = struct.unpack_from("<hhh", data, offset)
            samples.append(AccelSample(
                x=round(x_raw * scale, 4),
                y=round(y_raw * scale, 4),
                z=round(z_raw * scale, 4),
            ))
            offset += AccelDecoder.SAMPLE_SIZE

        if not samples:
            return None

        return AccelData(
            samples=samples,
            raw_payload=payload,
        )
