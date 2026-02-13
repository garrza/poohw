# Whoop 4.0 Sensor Data Formats

## Sensors

| Sensor | Type | Data | Notes |
|--------|------|------|-------|
| PPG (Photoplethysmography) | Optical | Raw waveform, HR, SpO2 | Green + red + IR LEDs |
| Accelerometer | MEMS 3-axis | x, y, z acceleration | Used for strain, activity, sleep detection |
| Skin Temperature | Thermistor | Degrees C | Continuous monitoring |
| SpO2 | Pulse oximetry | Blood oxygen % | Via red/IR LED ratio |

## Data Sources

### 1. Standard BLE Heart Rate (0x2A37)

Immediately available without proprietary protocol — just subscribe to HR_MEASUREMENT notifications.

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

### 2. Proprietary Realtime Data (packet type 0x28)

Enabled by TOGGLE_REALTIME_HR (cmd 0x03) — streams on DATA_FROM_STRAP.

### 3. Realtime IMU (packet type 0x33)

Enabled by TOGGLE_IMU_MODE (cmd 0x6A) — streams 3-axis accelerometer samples.

Format: Packed int16 LE triplets (x, y, z), scale factor 1/2048 → g (±16g range).

### 4. Historical Data (packet type 0x2F)

Requested via SEND_HISTORICAL_DATA (cmd 0x16). Contains multiple record subtypes.

### 5. Historical IMU (packet type 0x34)

Enabled by TOGGLE_IMU_MODE_HISTORICAL (cmd 0x69) — batched accelerometer data.

## Historical Record Formats

### 0x5C Comprehensive Record (~92 bytes)

The most information-dense format — combines HR, temperature, and SpO2 raw data:

| Offset | Size | Field | Encoding |
|--------|------|-------|----------|
| 0 | 4 | Timestamp | uint32 LE, Unix epoch seconds |
| 4 | 1 | Heart rate | uint8, bpm |
| 5 | 1 | RR count (N) | uint8 |
| 6 | 2×N | RR intervals | uint16 LE each, milliseconds |
| 22 | 12 | Temperature | LE integer / 100,000 → °C |
| 34 | ~50 | SpO2 raw | Suspected AC/DC red + IR values |

**Temperature**: `little_endian(record[22:34]) / 100_000` (per bWanShiTong).

**SpO2 raw section**: Likely 4× uint32 LE values at offset 34:
- `AC_red`, `DC_red`, `AC_ir`, `DC_ir`
- Ratio: `R = (AC_red / DC_red) / (AC_ir / DC_ir)`
- Beer-Lambert estimate: `SpO2 = 110 - 25 × R`

### 0x2F HR + RR Record

Simple HR snapshot with RR intervals:

| Offset | Size | Field |
|--------|------|-------|
| 0 | 4 | Timestamp (uint32 LE) |
| 4 | 1 | Heart rate (bpm) |
| 5 | 1 | RR count (N) |
| 6 | 2×N | RR intervals (uint16 LE, ms) |

### 0x30 Event Record

Discrete events (haptics fired, alarm, body-detect changes):

| Offset | Size | Field |
|--------|------|-------|
| 0 | 4 | Timestamp (uint32 LE) |
| 4 | 1 | Event ID |
| 5 | var | Event data |

### 0x34 Accelerometer Batch

| Offset | Size | Field |
|--------|------|-------|
| 0 | 4 | Timestamp (uint32 LE) |
| 4 | 6×N | Samples: int16 LE × 3 axes (x, y, z), scale 1/2048 → g |

## Derived Metrics

### HRV (Heart Rate Variability)

Computed from RR intervals (available from both standard BLE and proprietary sources):

- **RMSSD**: Root mean square of successive differences between RR intervals
- **HRV Score**: `ln(RMSSD) / 6.5 × 100` — maps to a ~0-100 scale

### Sleep Detection

Not a device command — computed locally from HR + accelerometer data:

1. Low HR (near resting) + low accelerometer magnitude → likely asleep
2. HR transitions + movement bursts → sleep stage boundaries
3. Well-studied problem: Cole-Kripke algorithm, Sadeh algorithm, etc.

### SpO2 from Raw Ratios

The band does not compute SpO2 on-device. Raw red/IR photodiode readings
must be processed using the Beer-Lambert calibration curve:

```
R = (AC_red / DC_red) / (AC_ir / DC_ir)
SpO2 = 110 - 25 × R
```

Valid for R ∈ [0.4, 1.0] → SpO2 ∈ [85%, 100%].

## Analysis Strategy

1. **Capture standard BLE HR** alongside proprietary packets for ground truth
2. **Request historical data** to get comprehensive 0x5C records
3. **Toggle IMU mode** for real-time or historical accelerometer data
4. **Cross-reference timestamps** between HR, accel, and temperature
5. **Implement algorithms locally**: HRV, sleep stages, SpO2 estimation
