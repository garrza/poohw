"""Heart rate / HRV decoder for Whoop proprietary packets."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from poohw.decoders.packet import WhoopPacket

from poohw.protocol import PacketType

# REALTIME_DATA (0x28) packets likely carry HR data.
# Command 0x03 (TOGGLE_REALTIME_HR) enables the stream.
HR_PACKET_TYPES = {PacketType.REALTIME_DATA, PacketType.REALTIME_RAW_DATA}


@dataclass
class HeartRateData:
    """Decoded heart rate data from a proprietary packet."""

    hr_bpm: int
    rr_intervals_ms: list[float]
    hrv_rmssd_ms: float | None = None
    timestamp_offset: int | None = None
    raw_payload: bytes = b""

    def __repr__(self) -> str:
        rr = f", rr={self.rr_intervals_ms}" if self.rr_intervals_ms else ""
        hrv = f", hrv={self.hrv_rmssd_ms:.1f}ms" if self.hrv_rmssd_ms else ""
        return f"HeartRateData(hr={self.hr_bpm}bpm{rr}{hrv})"


class HeartRateDecoder:
    """Decode heart rate data from Whoop proprietary packets.

    NOTE: The exact byte layout is based on initial RE findings and
    may need refinement as more captures are analyzed. The strategy is:
    - Try known offset patterns for HR value
    - Look for plausible HR values (30-220 bpm) at various offsets
    - Extract RR intervals if present
    """

    @staticmethod
    def can_decode(packet: WhoopPacket) -> bool:
        """Check if this packet likely contains HR data."""
        if packet.packet_type in HR_PACKET_TYPES:
            return True
        return False

    @staticmethod
    def decode(packet: WhoopPacket) -> HeartRateData | None:
        """Attempt to decode HR data from a proprietary packet.

        Tries multiple known/suspected byte layouts. Returns None if
        no plausible HR data found.
        """
        payload = packet.payload
        if len(payload) < 2:
            return None

        # Strategy: Try reading HR as uint8 at various offsets after the command byte
        # Common pattern: [cmd_id] [sub_cmd?] [hr_byte] [rr_data...]
        for offset in (1, 2, 3):
            if offset >= len(payload):
                continue
            candidate_hr = payload[offset]
            if 30 <= candidate_hr <= 220:
                rr_intervals = HeartRateDecoder._extract_rr_intervals(
                    payload, offset + 1
                )
                hrv = HeartRateDecoder._compute_rmssd(rr_intervals)
                return HeartRateData(
                    hr_bpm=candidate_hr,
                    rr_intervals_ms=rr_intervals,
                    hrv_rmssd_ms=hrv,
                    raw_payload=payload,
                )

        # Try uint16 LE at offset 1
        if len(payload) >= 3:
            candidate_hr = struct.unpack_from("<H", payload, 1)[0]
            if 30 <= candidate_hr <= 220:
                rr_intervals = HeartRateDecoder._extract_rr_intervals(payload, 3)
                hrv = HeartRateDecoder._compute_rmssd(rr_intervals)
                return HeartRateData(
                    hr_bpm=candidate_hr,
                    rr_intervals_ms=rr_intervals,
                    hrv_rmssd_ms=hrv,
                    raw_payload=payload,
                )

        return None

    @staticmethod
    def _extract_rr_intervals(payload: bytes, offset: int) -> list[float]:
        """Try to extract RR intervals as uint16 LE values from the given offset."""
        intervals: list[float] = []
        while offset + 1 < len(payload):
            raw = struct.unpack_from("<H", payload, offset)[0]
            # RR intervals typically 300-2000 ms.
            # Could be in ms directly or in 1/1024s units like standard BLE.
            if 200 <= raw <= 2500:
                intervals.append(float(raw))
            elif 200 <= (raw / 1.024) <= 2500:
                # 1/1024s units
                intervals.append(round(raw / 1.024, 1))
            offset += 2
        return intervals

    @staticmethod
    def _compute_rmssd(rr_intervals: list[float]) -> float | None:
        """Compute RMSSD (root mean square of successive differences)."""
        if len(rr_intervals) < 2:
            return None
        diffs = [rr_intervals[i + 1] - rr_intervals[i] for i in range(len(rr_intervals) - 1)]
        mean_sq = sum(d * d for d in diffs) / len(diffs)
        return round(mean_sq ** 0.5, 2)
