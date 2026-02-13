# poohw

Whoop 4.0 BLE reverse engineering toolkit.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requires Bluetooth permissions — grant access to your terminal in System Settings > Privacy & Security > Bluetooth.

## Usage

```bash
# Scan for Whoop devices
poohw scan

# Dump all BLE services/characteristics
poohw discover

# Stream live heart rate
poohw stream

# Capture raw BLE packets to file
poohw capture

# Replay and decode a capture file
poohw replay logs/capture_20240101_120000.jsonl

# Send a raw hex command
poohw send aa0800a8230e16001147c585
```

## Known Protocol Info

### BLE Services

The Whoop 4.0 exposes:
- **Standard Heart Rate Service** (0x180D) with Heart Rate Measurement (0x2A37)
- **Proprietary service** with custom characteristics:
  - `CMD_TO_STRAP`: `61080002-8d6d-82b8-614a-1c8cb0f8dcc6` (write)
  - `CMD_FROM_STRAP`: `61080003-8d6d-82b8-614a-1c8cb0f8dcc6` (notify)
  - `DATA_FROM_STRAP`: `61080004-8d6d-82b8-614a-1c8cb0f8dcc6` (notify)

### Packet Format

```
[aa] [length: 2 bytes] [command] [payload...] [checksum: 4 bytes]
```

- Header: `0xAA`
- Length: 16-bit, size of command + payload
- Checksum: 32-bit, algorithm not yet fully reversed

### Known Commands

- `aa0800a8230e16001147c585` — returns recent sensor data

## References

- [jogolden/whoomp](https://github.com/jogolden/whoomp) — Whoop firmware RE
- [bWanShiTong's research](https://github.com/bWanShiTong) — BLE protocol findings
