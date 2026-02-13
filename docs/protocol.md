# Whoop 4.0 BLE Protocol Reference

## BLE Services

### Standard Services

| Service | UUID | Notes |
|---------|------|-------|
| Heart Rate | 0x180D | Standard BLE HR profile (char 0x2A37) |
| Device Information | 0x180A | Model, firmware version, etc. |
| Battery | 0x180F | Battery level |

### Proprietary Service

Two UUID families exist depending on firmware generation:

| Family | Service UUID | Firmware |
|--------|-------------|----------|
| Gen1 | `61080001-8d6d-82b8-614a-1c8cb0f8dcc6` | Older |
| Gen2 | `fd4b0001-cce1-4033-93ce-002d5875f58a` | WG50 / firmware 50.x+ |

Both families use the same suffix pattern:

| Role | Suffix | Properties | Description |
|------|--------|------------|-------------|
| CMD_TO_STRAP | `0002` | write | Send commands to device |
| CMD_FROM_STRAP | `0003` | notify | Command responses |
| EVENTS_FROM_STRAP | `0004` | notify | Event notifications |
| DATA_FROM_STRAP | `0005` | notify | Sensor / bulk data |
| MEMFAULT | `0007` | notify | Crash diagnostics |

## Packet Format

```
[SOF: 0xAA] [LENGTH: 2B LE] [CRC8: 1B] [TYPE] [SEQ] [CMD] [DATA...] [CRC32: 4B LE]
```

### Fields

| Field | Size | Description |
|-------|------|-------------|
| SOF | 1 | Always `0xAA` |
| LENGTH | 2 | Little-endian uint16. Equals `len(TYPE+SEQ+CMD+DATA) + 4` (includes CRC32 trailer) |
| CRC8 | 1 | CRC-8 (polynomial 0x07) computed over the 2-byte LENGTH field |
| TYPE | 1 | Packet type (see table below) |
| SEQ | 1 | Sequence number (0x00 works fine for most commands) |
| CMD | 1 | Command ID or record subtype |
| DATA | var | Variable-length payload |
| CRC32 | 4 | Standard CRC-32 (zlib-compatible, LE) over `TYPE+SEQ+CMD+DATA` |

### Checksums (REVERSED)

Both checksums are fully reversed and implemented in `protocol.py`:

- **CRC-8**: Polynomial `0x07`, lookup-table implementation, computed over the 2-byte LENGTH field only.
- **CRC-32**: Standard zlib CRC-32 (`zlib.crc32() & 0xFFFFFFFF`), computed over the inner payload (`TYPE+SEQ+CMD+DATA`), stored as uint32 little-endian.

This means we can **build arbitrary packets from scratch** with valid checksums.

## Packet Types

| Value | Name | Direction | Description |
|-------|------|-----------|-------------|
| 0x23 | COMMAND | → strap | Send a command |
| 0x24 | COMMAND_RESPONSE | ← strap | Response to a command |
| 0x28 | REALTIME_DATA | ← strap | Streaming sensor data |
| 0x2B | REALTIME_RAW_DATA | ← strap | Raw optical/PPG data |
| 0x2F | HISTORICAL_DATA | ← strap | Buffered historical records |
| 0x30 | EVENT | ← strap | Discrete events (haptics, alarms, body-detect) |
| 0x31 | METADATA | ← strap | Device metadata |
| 0x32 | CONSOLE_LOGS | ← strap | Debug console output |
| 0x33 | REALTIME_IMU_DATA | ← strap | Streaming accelerometer |
| 0x34 | HISTORICAL_IMU_DATA | ← strap | Buffered accelerometer batches |

## Historical Data Record Subtypes

Within HISTORICAL_DATA (0x2F) packets, the CMD byte selects the record format:

| CMD byte | Name | Description |
|----------|------|-------------|
| 0x2F | HR_RR | Heart rate + RR intervals |
| 0x30 | EVENT | Discrete events |
| 0x34 | ACCEL_BATCH | Accelerometer sample batch |
| 0x5C | COMPREHENSIVE | Combined HR + temp + SpO2 raw + metadata (~92 bytes) |

### 0x5C Comprehensive Record Layout

The most information-dense record type. Field offsets assume typical RR count:

```
Offset  Size   Field
  0      4     Unix timestamp (uint32 LE)
  4      1     Heart rate (uint8, bpm)
  5      1     RR interval count (N)
  6     2*N    RR intervals (uint16 LE each, milliseconds)
  ...          (variable padding)
 22     12     Temperature (LE integer / 100,000 → °C)
 34     ~50    SpO2 raw data (suspected red/IR AC+DC ratios)
 84+     ?     Sequence counter / record CRC (under investigation)
```

Temperature decoding per bWanShiTong: `little_endian(record[22:34]) / 100_000`.

SpO2 raw section likely contains 4× uint32 values: `[AC_red, DC_red, AC_ir, DC_ir]`.
The ratio `R = (AC_red/DC_red) / (AC_ir/DC_ir)` maps to SpO2 via the empirical
Beer-Lambert curve: `SpO2 = 110 - 25 × R`.

## Key Commands

| ID | Name | Payload | Description |
|----|------|---------|-------------|
| 0x01 | LINK_VALID | — | Validate BLE link |
| 0x03 | TOGGLE_REALTIME_HR | `01`/`00` | Enable/disable realtime HR stream |
| 0x07 | REPORT_VERSION_INFO | — | Request firmware version |
| 0x0A | SET_CLOCK | uint32 LE epoch | Set device clock |
| 0x0B | GET_CLOCK | — | Read device clock |
| 0x14 | ABORT_HISTORICAL_TRANSMITS | — | Stop historical data download |
| 0x16 | SEND_HISTORICAL_DATA | — | Start historical data download |
| 0x17 | HISTORICAL_DATA_RESULT | — | Strap reports download status |
| 0x1A | GET_BATTERY_LEVEL | — | Query battery |
| 0x21 | SET_READ_POINTER | uint32 LE offset | Position read cursor |
| 0x22 | GET_DATA_RANGE | — | Query buffered data range |
| 0x44 | RUN_ALARM | `00` | Trigger alarm vibration |
| 0x4F | RUN_HAPTICS_PATTERN | `00` | Trigger haptic vibration |
| 0x69 | TOGGLE_IMU_MODE_HISTORICAL | `01`/`00` | Enable/disable historical IMU |
| 0x6A | TOGGLE_IMU_MODE | `01`/`00` | Enable/disable realtime IMU |
| 0x7A | STOP_HAPTICS | `00` | Stop vibration |
| 0x91 | GET_HELLO | — | Handshake / device info |

## Historical Data Workflow

To download buffered historical data from the strap:

```
1. GET_DATA_RANGE (0x22) → strap replies with min/max read pointers
2. SET_READ_POINTER (0x21, offset) → position cursor
3. SEND_HISTORICAL_DATA (0x16) → strap begins streaming HISTORICAL_DATA packets
4. (receive packets on DATA_FROM_STRAP notify characteristic)
5. ABORT_HISTORICAL_TRANSMITS (0x14) → stop early if needed
```

## Standard BLE Heart Rate (0x2A37)

Available without any proprietary protocol — just subscribe to notifications:

```
Byte 0: Flags
  Bit 0: HR format (0=uint8, 1=uint16)
  Bit 1-2: Sensor contact status
  Bit 3: Energy expended present
  Bit 4: RR-interval present

Byte 1+: HR value (uint8 or uint16 LE)
Optional: Energy expended (uint16 LE, kJ)
Optional: RR intervals (uint16 LE each, 1/1024 sec units)
```

### Derived Metrics

- **HRV (RMSSD)**: Root mean square of successive RR-interval differences
- **HRV Score**: `ln(RMSSD) / 6.5 × 100` — maps to a 0-100 scale used by consumer wearables

## References

- [jogolden/whoomp](https://github.com/jogolden/whoomp) — Firmware RE (packet format, CRC)
- [bWanShiTong](https://github.com/bWanShiTong) — BLE protocol research (temperature field, 0x5C record)
- [Bluetooth SIG Heart Rate Profile](https://www.bluetooth.com/specifications/specs/heart-rate-profile-1-0/)
