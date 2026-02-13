# poohw

Whoop 4.0 BLE reverse engineering toolkit.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requires Python >= 3.11 and Bluetooth permissions — grant access to your terminal in System Settings > Privacy & Security > Bluetooth.

## Commands

### Scanning & Discovery

```bash
# Scan for nearby Whoop devices
poohw scan [-t TIMEOUT]

# Dump all BLE services/characteristics to a file
poohw discover [-a ADDRESS] [-o OUTPUT]
```

### Live Streaming

```bash
# Stream live heart rate via the proprietary protocol
poohw stream [-a ADDRESS]

# Stream heart rate + accelerometer (IMU) data
poohw stream --imu
```

### Packet Capture & Replay

```bash
# Capture raw BLE packets (HR auto-enabled)
poohw capture [-a ADDRESS] [-d DURATION] [-o OUTPUT]

# Capture with IMU + historical data
poohw capture --imu --history -d 90 -o out.jsonl

# Passive capture (no HR enable)
poohw capture --no-hr

# Replay and decode a capture file
poohw replay logs/capture_*.jsonl [-o output.json] [-v] [--analyze]
```

### Analytics

```bash
# Run full analytics pipeline on a capture
poohw analyze logs/capture_*.jsonl [-o summary.json] [--max-hr 190] [--sleep-need 450]
```

### Commands & REPL

```bash
# Interactive REPL for sending commands
poohw repl [-a ADDRESS]

# Send a raw hex command
poohw send HEX_CMD [-a ADDRESS] [-t TIMEOUT]

# Make Whoop vibrate
poohw vibrate [-a ADDRESS] [-m haptics|alarm] [--all]

# Stop vibration
poohw stop-haptics [-a ADDRESS] [--all]

# Toggle IMU streaming on/off
poohw imu on|off [-a ADDRESS] [--historical]
```

### Data Retrieval

```bash
# Query buffered historical data range
poohw data-range [-a ADDRESS]

# Request historical data download
poohw history [-a ADDRESS] [-t TIMEOUT]
```

## Protocol

### Proprietary BLE Service

The Whoop 4.0 uses a proprietary BLE service for all sensor data. Two UUID families exist:

| Role | Gen1 (older firmware) | Gen2 (WG50 / firmware 50.x) |
|------|----------------------|----------------------------|
| Service | `61080001-...` | `fd4b0001-...` |
| CMD_TO_STRAP (write) | `61080002-...` | `fd4b0002-...` |
| CMD_FROM_STRAP (notify) | `61080003-...` | `fd4b0003-...` |
| EVENTS_FROM_STRAP (notify) | `61080004-...` | `fd4b0004-...` |
| DATA_FROM_STRAP (notify) | `61080005-...` | `fd4b0005-...` |

### Packet Format

```
[SOF: 0xAA] [LENGTH: 2B LE] [CRC8: 1B] [TYPE] [SEQ] [CMD] [DATA...] [CRC32: 4B LE]
```

### REALTIME_DATA HR Format (0x28)

Confirmed layout from WG50 captures:

| Offset | Size | Field |
|--------|------|-------|
| 0-3 | 4B | Internal timestamp counter |
| 4-5 | 2B | HR as uint16 LE (÷256 = BPM) |
| 6 | 1B | RR interval count (0-2) |
| 7-8 | 2B | RR interval 1 (ms) |
| 9-10 | 2B | RR interval 2 (ms) |
| 11-14 | 4B | Reserved |
| 15 | 1B | Wearing flag |
| 16 | 1B | Sensor status |

## References

- [jogolden/whoomp](https://github.com/jogolden/whoomp) — Whoop firmware RE
- [bWanShiTong's research](https://github.com/bWanShiTong) — BLE protocol findings
