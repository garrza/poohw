"""Tests for replay.py — decode_packet pipeline and replay_file."""

from __future__ import annotations

import base64
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
from poohw.decoders.packet import PacketDecoder
from poohw.replay import decode_packet, replay_file, DECODERS

from tests.conftest import (
    make_realtime_packet,
    make_historical_packet,
    make_command_packet,
    make_imu_packet,
    make_comprehensive_payload,
    write_jsonl,
    make_capture_entry,
)

# Proprietary UUIDs for test entries
GEN1_DATA_UUID = "61080005-8d6d-82b8-614a-1c8cb0f8dcc6"
GEN1_CMD_FROM_UUID = "61080003-8d6d-82b8-614a-1c8cb0f8dcc6"
STANDARD_HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


# ===================================================================
# decode_packet pipeline
# ===================================================================


class TestDecodePacket:
    def test_realtime_data_matches_hr_temp_spo2(self):
        """A REALTIME_DATA packet can match HR, temp, and SpO2 decoders."""
        # Craft a payload where byte[1] is a valid HR (72) and also
        # could match temperature (uint16 at [1:3] → 72 + 256*X)
        payload = bytes([0x00, 72])
        wp = make_realtime_packet(data=payload)
        results = decode_packet(wp)
        # At minimum HR should match
        types = {r["type"] for r in results}
        assert "heart_rate" in types

    def test_historical_data_matches_historical_decoder(self):
        """HISTORICAL_DATA packets match the historical decoder."""
        payload = make_comprehensive_payload()
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        results = decode_packet(wp)
        types = {r["type"] for r in results}
        assert "historical" in types

    def test_command_packet_no_decode(self):
        """COMMAND packets don't match any sensor decoder."""
        wp = make_command_packet()
        results = decode_packet(wp)
        assert results == []

    def test_imu_packet_matches_accel(self):
        """REALTIME_IMU_DATA matches the accelerometer decoder."""
        sample = struct.pack("<hhh", 2048, 0, 0)
        wp = make_imu_packet(data=b"\x00" + sample)
        results = decode_packet(wp)
        types = {r["type"] for r in results}
        assert "accelerometer" in types

    def test_historical_decoder_is_first(self):
        """The historical decoder should be listed first in DECODERS."""
        assert DECODERS[0][0] == "historical"


# ===================================================================
# replay_file
# ===================================================================


class TestReplayFile:
    def test_nonexistent_file(self, capsys):
        result = replay_file("/nonexistent/path/to/file.jsonl")
        assert result == []
        out = capsys.readouterr().out
        assert "File not found" in out

    def test_empty_file(self, tmp_path, capsys):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        result = replay_file(str(f))
        assert result == []
        out = capsys.readouterr().out
        assert "0 total packets" in out

    def test_standard_uuid_skipped(self, tmp_path, capsys):
        """Non-proprietary UUIDs are skipped during replay."""
        entries = [
            make_capture_entry(STANDARD_HR_UUID, "1648"),
        ]
        f = write_jsonl(tmp_path / "capture.jsonl", entries)
        result = replay_file(str(f))
        # No proprietary packets → no records
        assert result == []
        out = capsys.readouterr().out
        assert "1 total packets" in out
        assert "0 proprietary" in out

    def test_proprietary_packet_decoded(self, tmp_path, capsys):
        """A valid proprietary packet is decoded."""
        # Build a REALTIME_DATA packet with an HR-like payload
        pkt = build_packet(PacketType.REALTIME_DATA, 0x00, bytes([0x00, 72]))
        entries = [
            make_capture_entry(GEN1_DATA_UUID, pkt.hex()),
        ]
        f = write_jsonl(tmp_path / "capture.jsonl", entries)
        result = replay_file(str(f))
        assert len(result) == 1
        out = capsys.readouterr().out
        assert "1 proprietary" in out

    def test_raw_bytes_b64_format(self, tmp_path, capsys):
        """Entries with raw_bytes_b64 field are decoded."""
        pkt = build_packet(PacketType.REALTIME_DATA, 0x00, bytes([0x00, 80]))
        entry = {
            "uuid": GEN1_DATA_UUID,
            "raw_bytes_b64": base64.b64encode(pkt).decode(),
            "timestamp": "2024-02-13T12:00:00Z",
        }
        f = write_jsonl(tmp_path / "capture.jsonl", [entry])
        result = replay_file(str(f))
        assert len(result) == 1

    def test_invalid_json_skipped(self, tmp_path, capsys):
        """Lines with invalid JSON are skipped."""
        f = tmp_path / "capture.jsonl"
        f.write_text("not json\n")
        result = replay_file(str(f))
        assert result == []
        out = capsys.readouterr().out
        assert "0 total packets" in out

    def test_invalid_json_verbose(self, tmp_path, capsys):
        """In verbose mode, invalid JSON generates a warning."""
        f = tmp_path / "capture.jsonl"
        f.write_text("not json\n")
        replay_file(str(f), verbose=True)
        out = capsys.readouterr().out
        assert "Invalid JSON" in out

    def test_invalid_packet_verbose(self, tmp_path, capsys):
        """Non-valid packets get a verbose message."""
        entries = [
            make_capture_entry(GEN1_DATA_UUID, "0102030405"),  # not a valid Whoop packet
        ]
        f = write_jsonl(tmp_path / "capture.jsonl", entries)
        replay_file(str(f), verbose=True)
        out = capsys.readouterr().out
        assert "not a valid packet" in out

    def test_output_file(self, tmp_path, capsys):
        """Decoded results are written to the output file as JSON."""
        pkt = build_packet(PacketType.REALTIME_DATA, 0x00, bytes([0x00, 72]))
        entries = [make_capture_entry(GEN1_DATA_UUID, pkt.hex())]
        capture_f = write_jsonl(tmp_path / "capture.jsonl", entries)
        output_f = tmp_path / "decoded.json"

        replay_file(str(capture_f), output_path=str(output_f))
        out = capsys.readouterr().out
        assert "Output written to" in out

        decoded = json.loads(output_f.read_text())
        assert isinstance(decoded, list)
        assert len(decoded) >= 1

    def test_mixed_entries(self, tmp_path, capsys):
        """Mix of standard, proprietary, and invalid entries."""
        pkt = build_packet(PacketType.REALTIME_DATA, 0x00, bytes([0x00, 72]))
        entries = [
            make_capture_entry(STANDARD_HR_UUID, "1648"),       # standard → skip
            make_capture_entry(GEN1_DATA_UUID, pkt.hex()),      # proprietary → decode
            make_capture_entry(GEN1_DATA_UUID, "0102030405"),   # bad packet → skip
        ]
        f = write_jsonl(tmp_path / "capture.jsonl", entries)
        result = replay_file(str(f))
        out = capsys.readouterr().out
        assert "3 total packets" in out
        assert "2 proprietary" in out  # 2 proprietary entries (1 valid, 1 invalid)

    def test_entry_without_raw_data_skipped(self, tmp_path, capsys):
        """Entries missing both hex_data and raw_bytes_b64 are skipped."""
        entries = [
            {"uuid": GEN1_DATA_UUID, "timestamp": "2024-02-13T12:00:00Z"},
        ]
        f = write_jsonl(tmp_path / "capture.jsonl", entries)
        result = replay_file(str(f))
        assert result == []

    def test_verbose_standard_uuid(self, tmp_path, capsys):
        """Verbose mode prints a message for standard UUIDs."""
        entries = [make_capture_entry(STANDARD_HR_UUID, "1648")]
        f = write_jsonl(tmp_path / "capture.jsonl", entries)
        replay_file(str(f), verbose=True)
        out = capsys.readouterr().out
        assert "standard, skipping" in out

    def test_verbose_undecoded_proprietary(self, tmp_path, capsys):
        """Verbose mode prints undecoded proprietary packets."""
        # A COMMAND packet won't match any decoder
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        entries = [make_capture_entry(GEN1_CMD_FROM_UUID, pkt.hex())]
        f = write_jsonl(tmp_path / "capture.jsonl", entries)
        replay_file(str(f), verbose=True)
        out = capsys.readouterr().out
        assert "no decoder matched" in out
