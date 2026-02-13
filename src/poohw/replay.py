"""Replay captured packet logs through decoders for offline analysis."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from poohw.decoders.packet import PacketDecoder, WhoopPacket
from poohw.decoders.hr import HeartRateDecoder
from poohw.decoders.accel import AccelDecoder
from poohw.decoders.temperature import TemperatureDecoder
from poohw.decoders.spo2 import SpO2Decoder
from poohw.decoders.historical import HistoricalDecoder
from poohw.protocol import is_proprietary_uuid


# Ordered list of decoders — historical first since it's the most specific
# for HISTORICAL_DATA packets and avoids false positives from the heuristic
# decoders (hr/temp/spo2) that guess at byte layouts.
DECODERS = [
    ("historical", HistoricalDecoder),
    ("heart_rate", HeartRateDecoder),
    ("accelerometer", AccelDecoder),
    ("temperature", TemperatureDecoder),
    ("spo2", SpO2Decoder),
]


def decode_packet(packet: WhoopPacket) -> list[dict]:
    """Run a packet through all decoders. Returns list of successful decodes."""
    results = []
    for name, decoder_cls in DECODERS:
        if decoder_cls.can_decode(packet):
            decoded = decoder_cls.decode(packet)
            if decoded is not None:
                results.append({"type": name, "data": decoded})
    return results


def replay_file(
    capture_path: str,
    output_path: str | None = None,
    verbose: bool = False,
) -> list[dict]:
    """Replay a .jsonl capture file through all decoders.

    Args:
        capture_path: Path to the .jsonl capture file.
        output_path: Optional path to write decoded output as JSON.
        verbose: If True, print all packets including undecoded ones.

    Returns:
        List of decoded records.
    """
    path = Path(capture_path)
    if not path.exists():
        print(f"File not found: {capture_path}")
        return []

    records: list[dict] = []
    total = 0
    decoded_count = 0
    proprietary_count = 0

    print(f"Replaying {path.name}...\n")

    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                if verbose:
                    print(f"  [line {line_num}] Invalid JSON, skipping")
                continue

            total += 1
            uuid = entry.get("uuid", "")
            timestamp = entry.get("timestamp", "?")

            # Get raw bytes
            if "raw_bytes_b64" in entry:
                raw = base64.b64decode(entry["raw_bytes_b64"])
            elif "hex_data" in entry:
                raw = bytes.fromhex(entry["hex_data"])
            else:
                continue

            # Only try to decode proprietary packets
            is_proprietary = is_proprietary_uuid(uuid)

            if not is_proprietary:
                if verbose:
                    print(f"  [{timestamp}] {uuid[:12]}... (standard, skipping decode)")
                continue

            proprietary_count += 1
            packet = PacketDecoder.decode(raw)

            if packet is None:
                if verbose:
                    print(f"  [{timestamp}] raw={raw.hex()} (not a valid packet)")
                continue

            results = decode_packet(packet)

            record = {
                "line": line_num,
                "timestamp": timestamp,
                "uuid": uuid,
                "packet": str(packet),
                "raw_hex": raw.hex(),
                "decoded": [],
            }

            if results:
                decoded_count += 1
                for r in results:
                    record["decoded"].append({
                        "type": r["type"],
                        "data": str(r["data"]),
                    })
                    print(f"  [{timestamp}] {r['type']}: {r['data']}")
            elif verbose:
                print(f"  [{timestamp}] {packet} (no decoder matched)")

            records.append(record)

    print(f"\nSummary: {total} total packets, {proprietary_count} proprietary, "
          f"{decoded_count} decoded")

    if output_path:
        with open(output_path, "w") as out:
            json.dump(records, out, indent=2)
        print(f"Output written to {output_path}")

    return records


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m poohw.replay <capture_file.jsonl> [output.json]")
        sys.exit(1)

    capture_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    replay_file(capture_path, output_path, verbose)


if __name__ == "__main__":
    main()
