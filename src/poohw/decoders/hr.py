"""Heart rate / HRV decoder for Whoop proprietary packets.

Confirmed REALTIME_DATA (0x28) payload layout (17 bytes):
    [0:4]   Timestamp (internal counter, 4 bytes)
    [4:6]   HR as uint16 LE — divide by 256 for BPM with sub-beat precision
    [6]     RR interval count (0, 1, or 2)
    [7:9]   RR interval 1 (uint16 LE, milliseconds)
    [9:11]  RR interval 2 (uint16 LE, milliseconds) — only if count >= 2
    [11:15] Reserved (zeros)
    [15]    Wearing flag (0x01 = on wrist)
    [16]    Sensor status flag (0x01 = OK)

Validated against real captures from a WG50 (firmware 50.35.3.0).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from poohw.decoders.packet import WhoopPacket

from poohw.protocol import PacketType

# REALTIME_DATA (0x28) packets carry HR data when enabled via
# TOGGLE_REALTIME_HR (0x03).
HR_PACKET_TYPES = {PacketType.REALTIME_DATA, PacketType.REALTIME_RAW_DATA}

# Minimum payload size for REALTIME_DATA HR packets.
# 4 (timestamp) + 2 (HR u16) + 1 (RR count) = 7 bytes minimum.
_MIN_PAYLOAD_SIZE = 7


@dataclass
class HeartRateData:
    """Decoded heart rate data from a proprietary packet."""

    hr_bpm: int
    hr_precise: float
    rr_intervals_ms: list[float]
    rr_count: int = 0
    hrv_rmssd_ms: float | None = None
    wearing: bool = True
    timestamp_raw: int = 0
    raw_payload: bytes = b""

    def __repr__(self) -> str:
        rr = f", rr={self.rr_intervals_ms}" if self.rr_intervals_ms else ""
        hrv = f", hrv={self.hrv_rmssd_ms:.1f}ms" if self.hrv_rmssd_ms else ""
        return f"HeartRateData(hr={self.hr_bpm}bpm ({self.hr_precise:.1f}){rr}{hrv})"


class HeartRateDecoder:
    """Decode heart rate data from Whoop REALTIME_DATA packets.

    The byte layout was reverse-engineered from real WG50 captures.
    HR is encoded as uint16 LE at payload offset 4, in 1/256 BPM units.
    RR intervals follow as uint16 LE values in milliseconds, preceded
    by a count byte at offset 6.
    """

    @staticmethod
    def can_decode(packet: WhoopPacket) -> bool:
        """Check if this packet contains HR data."""
        return packet.packet_type in HR_PACKET_TYPES

    @staticmethod
    def decode(packet: WhoopPacket) -> HeartRateData | None:
        """Decode HR data from a REALTIME_DATA packet.

        Returns None if the payload is too short or HR value is implausible.
        """
        payload = packet.payload
        if len(payload) < _MIN_PAYLOAD_SIZE:
            return None

        # Timestamp (bytes 0-3) — internal counter, not Unix epoch
        timestamp_raw = struct.unpack_from("<I", payload, 0)[0]

        # HR: uint16 LE at offset 4, in 1/256 BPM units
        hr_raw = struct.unpack_from("<H", payload, 4)[0]
        hr_precise = hr_raw / 256.0
        hr_bpm = round(hr_precise)

        if hr_bpm < 1 or hr_bpm > 250:
            return None

        # RR interval count at offset 6
        rr_count = payload[6]
        rr_intervals: list[float] = []

        if rr_count > 0 and len(payload) >= 9:
            rr1 = struct.unpack_from("<H", payload, 7)[0]
            if 200 <= rr1 <= 2500:
                rr_intervals.append(float(rr1))

        if rr_count > 1 and len(payload) >= 11:
            rr2 = struct.unpack_from("<H", payload, 9)[0]
            if 200 <= rr2 <= 2500:
                rr_intervals.append(float(rr2))

        # Wearing flag at offset 15
        wearing = payload[15] == 0x01 if len(payload) > 15 else True

        # Compute HRV (RMSSD) if we have enough RR intervals
        hrv = HeartRateDecoder._compute_rmssd(rr_intervals)

        return HeartRateData(
            hr_bpm=hr_bpm,
            hr_precise=round(hr_precise, 2),
            rr_intervals_ms=rr_intervals,
            rr_count=rr_count,
            hrv_rmssd_ms=hrv,
            wearing=wearing,
            timestamp_raw=timestamp_raw,
            raw_payload=payload,
        )

    @staticmethod
    def _compute_rmssd(rr_intervals: list[float]) -> float | None:
        """Compute RMSSD (root mean square of successive differences)."""
        if len(rr_intervals) < 2:
            return None
        diffs = [rr_intervals[i + 1] - rr_intervals[i] for i in range(len(rr_intervals) - 1)]
        mean_sq = sum(d * d for d in diffs) / len(diffs)
        return round(mean_sq ** 0.5, 2)
