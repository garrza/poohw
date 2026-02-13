"""Historical data record decoder for Whoop proprietary packets.

The Whoop buffers sensor data on-device and transmits it in bulk when
requested via SEND_HISTORICAL_DATA (cmd 0x16).  Records arrive as
HISTORICAL_DATA (packet type 0x2F) packets.  The command byte within the
packet selects the record subtype.

The most information-dense subtype is 0x5C ("comprehensive"), which packs
HR, RR intervals, skin temperature, and likely SpO2 raw photo-diode ratios
into a single ~92-byte record.

Field layout for the 0x5C record (per bWanShiTong research + RE):
------------------------------------------------------------------------
Offset  Size   Field
  0      4     Unix timestamp (uint32 LE) — sample epoch seconds
  4      1     Heart rate (uint8, bpm)
  5      1     RR interval count (N)
  6     2*N    RR intervals (uint16 LE each, milliseconds)
 6+2N    2     Stride / step count? (uint16 LE) — still under investigation
 ...          (variable gap depending on N)
 22     12     Temperature raw (little-endian bytes, /100_000 → °C)
 34     ~50    Unknown — suspected SpO2 red/IR ratio + metadata
 84      4     Sequence / record counter? (uint32 LE)
 88      4     CRC or hash of the record body?

The exact boundaries shift depending on the RR interval count, so the
above offsets assume N == 8 (typical resting).  The decoder is designed
to be lenient and extract what it can.
------------------------------------------------------------------------
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

from poohw.decoders.packet import WhoopPacket
from poohw.protocol import PacketType, HistoricalRecordType

# Re-export HRV / SpO2 helpers from the analytics layer.
# They originally lived here; keep the old import paths working.
from poohw.analytics.features import (  # noqa: F401
    compute_rmssd,
    lnrmssd_score,
)
from poohw.analytics.spo2 import estimate_spo2_from_ratio  # noqa: F401


# Packet types that carry historical data
HISTORICAL_PACKET_TYPES = {
    PacketType.HISTORICAL_DATA,
    PacketType.HISTORICAL_IMU_DATA,
}


# ---------------------------------------------------------------------------
# Data classes for decoded records
# ---------------------------------------------------------------------------


@dataclass
class HistoricalHRRecord:
    """A single HR + RR snapshot from a historical record."""

    timestamp: int  # Unix epoch seconds
    hr_bpm: int
    rr_intervals_ms: list[float]
    hrv_rmssd_ms: float | None = None
    hrv_lnrmssd_score: float | None = None  # ln(RMSSD) / 6.5 * 100

    def __repr__(self) -> str:
        rr = f", rr={self.rr_intervals_ms}" if self.rr_intervals_ms else ""
        hrv = f", hrv={self.hrv_rmssd_ms:.1f}ms" if self.hrv_rmssd_ms else ""
        score = f", score={self.hrv_lnrmssd_score:.1f}" if self.hrv_lnrmssd_score else ""
        return f"HistHR(t={self.timestamp}, hr={self.hr_bpm}bpm{rr}{hrv}{score})"


@dataclass
class HistoricalTempRecord:
    """Temperature extracted from a historical record."""

    timestamp: int
    skin_temp_c: float
    skin_temp_f: float
    raw_bytes: bytes = b""

    def __repr__(self) -> str:
        return f"HistTemp(t={self.timestamp}, skin={self.skin_temp_c:.2f}°C)"


@dataclass
class HistoricalSpO2RawRecord:
    """Raw SpO2-related bytes from a historical record (not yet decoded to %)."""

    timestamp: int
    raw_bytes: bytes  # the undecoded ~50-byte section
    red_ir_ratio: float | None = None  # if we can extract the R value
    estimated_spo2: float | None = None  # Beer-Lambert estimate

    def __repr__(self) -> str:
        spo2 = f", spo2≈{self.estimated_spo2:.1f}%" if self.estimated_spo2 else ""
        return f"HistSpO2Raw(t={self.timestamp}, {len(self.raw_bytes)}B{spo2})"


@dataclass
class ComprehensiveRecord:
    """Fully decoded 0x5C comprehensive historical record."""

    timestamp: int
    hr: HistoricalHRRecord | None = None
    temperature: HistoricalTempRecord | None = None
    spo2_raw: HistoricalSpO2RawRecord | None = None
    unknown_bytes: bytes = b""
    raw_payload: bytes = b""

    def __repr__(self) -> str:
        parts = [f"t={self.timestamp}"]
        if self.hr:
            parts.append(f"hr={self.hr.hr_bpm}bpm")
        if self.temperature:
            parts.append(f"temp={self.temperature.skin_temp_c:.2f}°C")
        if self.spo2_raw and self.spo2_raw.estimated_spo2:
            parts.append(f"spo2≈{self.spo2_raw.estimated_spo2:.1f}%")
        return f"ComprehensiveRecord({', '.join(parts)})"


@dataclass
class HistoricalAccelBatch:
    """Accelerometer batch from a HISTORICAL_IMU_DATA packet."""

    timestamp: int
    samples: list[tuple[float, float, float]]  # (x, y, z) in g
    raw_payload: bytes = b""

    def __repr__(self) -> str:
        return f"HistAccelBatch(t={self.timestamp}, {len(self.samples)} samples)"


@dataclass
class HistoricalEventRecord:
    """A discrete event from a historical EVENT packet."""

    timestamp: int
    event_id: int
    event_data: bytes = b""

    def __repr__(self) -> str:
        return f"HistEvent(t={self.timestamp}, id=0x{self.event_id:02X}, data={self.event_data.hex()})"


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


class HistoricalDecoder:
    """Decode historical data records from Whoop proprietary packets."""

    @staticmethod
    def can_decode(packet: WhoopPacket) -> bool:
        """Check if this packet carries historical data."""
        return packet.packet_type in HISTORICAL_PACKET_TYPES

    @staticmethod
    def decode(packet: WhoopPacket) -> (
        ComprehensiveRecord
        | HistoricalHRRecord
        | HistoricalAccelBatch
        | HistoricalEventRecord
        | dict
        | None
    ):
        """Decode a historical data packet.

        Dispatches to the appropriate sub-decoder based on the command byte
        (record subtype).  Returns a typed record or a generic dict for
        unknown subtypes.
        """
        if not HistoricalDecoder.can_decode(packet):
            return None

        payload = packet.payload
        cmd = packet.command_id

        # Historical IMU data gets its own packet type
        if packet.packet_type == PacketType.HISTORICAL_IMU_DATA:
            return HistoricalDecoder._decode_accel_batch(payload)

        # Dispatch by command byte (record subtype)
        if cmd == HistoricalRecordType.COMPREHENSIVE:
            return HistoricalDecoder._decode_comprehensive(payload)
        elif cmd == HistoricalRecordType.HR_RR:
            return HistoricalDecoder._decode_hr_rr(payload)
        elif cmd == HistoricalRecordType.EVENT:
            return HistoricalDecoder._decode_event(payload)
        elif cmd == HistoricalRecordType.ACCEL_BATCH:
            return HistoricalDecoder._decode_accel_batch(payload)
        else:
            # Unknown subtype — return a generic dict so nothing is lost
            return HistoricalDecoder._decode_generic(cmd, payload)

    # -----------------------------------------------------------------------
    # 0x5C — Comprehensive record
    # -----------------------------------------------------------------------

    @staticmethod
    def _decode_comprehensive(payload: bytes) -> ComprehensiveRecord | None:
        """Decode a 0x5C comprehensive historical record.

        Layout (best current understanding):
            [0:4]    uint32 LE  timestamp (epoch seconds)
            [4]      uint8      heart rate (bpm)
            [5]      uint8      RR interval count (N)
            [6:6+2N] uint16 LE  RR intervals (ms each)
            ... variable gap ...
            [22:34]  12 bytes   temperature (LE bytes / 100_000 → °C)
            [34:84]  ~50 bytes  unknown — likely SpO2 raw red/IR data
        """
        if len(payload) < 6:
            return None

        # --- Timestamp ---
        timestamp = 0
        if len(payload) >= 4:
            timestamp = struct.unpack_from("<I", payload, 0)[0]

        # --- Heart rate ---
        hr_bpm = payload[4] if len(payload) > 4 else 0

        # --- RR intervals ---
        rr_count = payload[5] if len(payload) > 5 else 0
        rr_intervals: list[float] = []
        rr_end = 6 + rr_count * 2
        if rr_count > 0 and len(payload) >= rr_end:
            for i in range(rr_count):
                offset = 6 + i * 2
                rr_ms = struct.unpack_from("<H", payload, offset)[0]
                rr_intervals.append(float(rr_ms))

        # --- HR record with HRV ---
        hrv = compute_rmssd(rr_intervals)
        score = lnrmssd_score(hrv) if hrv is not None else None
        hr_record = HistoricalHRRecord(
            timestamp=timestamp,
            hr_bpm=hr_bpm,
            rr_intervals_ms=rr_intervals,
            hrv_rmssd_ms=hrv,
            hrv_lnrmssd_score=score,
        )

        # --- Temperature ---
        # Per bWanShiTong: temperature = little_endian(packet[22:34]) / 100_000
        # These offsets are into the full packet payload.
        temp_record = None
        temp_start = 22
        temp_end = 34
        if len(payload) >= temp_end:
            temp_bytes = payload[temp_start:temp_end]
            temp_record = HistoricalDecoder._decode_temperature_bytes(
                timestamp, temp_bytes
            )

        # --- SpO2 raw section ---
        # The ~50 undecoded bytes after the temperature section
        spo2_record = None
        spo2_start = 34
        spo2_end = min(spo2_start + 50, len(payload))
        if len(payload) > spo2_start:
            spo2_bytes = payload[spo2_start:spo2_end]
            spo2_record = HistoricalDecoder._decode_spo2_raw(
                timestamp, spo2_bytes
            )

        # --- Remaining unknown bytes ---
        unknown = payload[spo2_end:] if len(payload) > spo2_end else b""

        return ComprehensiveRecord(
            timestamp=timestamp,
            hr=hr_record,
            temperature=temp_record,
            spo2_raw=spo2_record,
            unknown_bytes=unknown,
            raw_payload=payload,
        )

    @staticmethod
    def _decode_temperature_bytes(
        timestamp: int, raw: bytes
    ) -> HistoricalTempRecord | None:
        """Decode 12 temperature bytes (little-endian integer / 100_000 → °C).

        The 12-byte field can represent a very large integer, but skin
        temperature should be in [25, 45] °C.  We try progressively smaller
        windows in case not all 12 bytes contribute.
        """
        # Try full 12 bytes first, then smaller windows
        for width in (12, 8, 6, 4, 2):
            chunk = raw[:width]
            # Pad to 8 bytes for uint64 unpack (or handle smaller)
            if width <= 8:
                padded = chunk.ljust(8, b"\x00")
                raw_val = struct.unpack("<Q", padded)[0]
            else:
                # For 12 bytes, interpret as uint64 (lower 8) + uint32 (upper 4)
                lo = struct.unpack_from("<Q", chunk, 0)[0]
                hi = struct.unpack_from("<I", chunk, 8)[0]
                raw_val = lo | (hi << 64)

            temp_c = raw_val / 100_000.0
            if 25.0 <= temp_c <= 45.0:
                return HistoricalTempRecord(
                    timestamp=timestamp,
                    skin_temp_c=round(temp_c, 4),
                    skin_temp_f=round(temp_c * 9.0 / 5.0 + 32.0, 4),
                    raw_bytes=raw,
                )

        return None

    @staticmethod
    def _decode_spo2_raw(
        timestamp: int, raw: bytes
    ) -> HistoricalSpO2RawRecord | None:
        """Attempt to extract a red/IR ratio from the raw SpO2 bytes.

        Strategy: Look for pairs of uint32 values that could be AC/DC
        measurements for red and IR channels.  The ratio R = (AC_r/DC_r) /
        (AC_ir/DC_ir) typically falls in [0.4, 1.0] for SpO2 85-100%.

        This is speculative — we log the raw bytes either way so they can
        be analyzed offline.
        """
        if len(raw) < 8:
            return HistoricalSpO2RawRecord(
                timestamp=timestamp,
                raw_bytes=raw,
            )

        # Heuristic: try reading first 4 uint32 values as
        # [ac_red, dc_red, ac_ir, dc_ir]
        ratio = None
        spo2 = None
        if len(raw) >= 16:
            vals = struct.unpack_from("<IIII", raw, 0)
            ac_red, dc_red, ac_ir, dc_ir = vals
            if dc_red > 0 and dc_ir > 0 and ac_ir > 0:
                r = (ac_red / dc_red) / (ac_ir / dc_ir)
                if 0.2 <= r <= 1.5:
                    ratio = round(r, 4)
                    spo2 = estimate_spo2_from_ratio(r)

        return HistoricalSpO2RawRecord(
            timestamp=timestamp,
            raw_bytes=raw,
            red_ir_ratio=ratio,
            estimated_spo2=spo2,
        )

    # -----------------------------------------------------------------------
    # 0x2F — HR + RR record
    # -----------------------------------------------------------------------

    @staticmethod
    def _decode_hr_rr(payload: bytes) -> HistoricalHRRecord | None:
        """Decode a simple HR + RR intervals historical record."""
        if len(payload) < 5:
            return None

        timestamp = struct.unpack_from("<I", payload, 0)[0]
        hr_bpm = payload[4]
        rr_intervals: list[float] = []

        if len(payload) > 5:
            rr_count = payload[5]
            for i in range(rr_count):
                offset = 6 + i * 2
                if offset + 2 > len(payload):
                    break
                rr_ms = struct.unpack_from("<H", payload, offset)[0]
                rr_intervals.append(float(rr_ms))

        hrv = compute_rmssd(rr_intervals)
        score = lnrmssd_score(hrv) if hrv is not None else None

        return HistoricalHRRecord(
            timestamp=timestamp,
            hr_bpm=hr_bpm,
            rr_intervals_ms=rr_intervals,
            hrv_rmssd_ms=hrv,
            hrv_lnrmssd_score=score,
        )

    # -----------------------------------------------------------------------
    # 0x34 / IMU — Accelerometer batch
    # -----------------------------------------------------------------------

    ACCEL_SCALE = 1.0 / 2048.0  # int16 → g (±16g range)

    @staticmethod
    def _decode_accel_batch(payload: bytes) -> HistoricalAccelBatch | None:
        """Decode a batch of 3-axis accelerometer samples."""
        if len(payload) < 10:
            return None

        timestamp = struct.unpack_from("<I", payload, 0)[0]
        data = payload[4:]
        sample_size = 6  # 3 axes × int16
        samples: list[tuple[float, float, float]] = []
        scale = HistoricalDecoder.ACCEL_SCALE

        offset = 0
        while offset + sample_size <= len(data):
            x, y, z = struct.unpack_from("<hhh", data, offset)
            samples.append((
                round(x * scale, 4),
                round(y * scale, 4),
                round(z * scale, 4),
            ))
            offset += sample_size

        if not samples:
            return None

        return HistoricalAccelBatch(
            timestamp=timestamp,
            samples=samples,
            raw_payload=payload,
        )

    # -----------------------------------------------------------------------
    # 0x30 — Event record
    # -----------------------------------------------------------------------

    @staticmethod
    def _decode_event(payload: bytes) -> HistoricalEventRecord | None:
        """Decode a discrete event record."""
        if len(payload) < 5:
            return None

        timestamp = struct.unpack_from("<I", payload, 0)[0]
        event_id = payload[4]
        event_data = payload[5:]

        return HistoricalEventRecord(
            timestamp=timestamp,
            event_id=event_id,
            event_data=event_data,
        )

    # -----------------------------------------------------------------------
    # Unknown subtype
    # -----------------------------------------------------------------------

    @staticmethod
    def _decode_generic(cmd: int | None, payload: bytes) -> dict:
        """Return a dict for unknown historical record subtypes."""
        timestamp = 0
        if len(payload) >= 4:
            timestamp = struct.unpack_from("<I", payload, 0)[0]

        return {
            "type": "unknown_historical",
            "subtype": cmd,
            "timestamp": timestamp,
            "payload_hex": payload.hex(),
            "payload_len": len(payload),
        }
