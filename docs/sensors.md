# Whoop 4.0 Sensor Data Formats

## Sensors

The Whoop 4.0 contains the following sensors:

| Sensor | Type | Data | Notes |
|--------|------|------|-------|
| PPG (Photoplethysmography) | Optical | Raw waveform, HR, SpO2 | Green + red + IR LEDs |
| Accelerometer | MEMS 3-axis | x, y, z acceleration | Used for strain, activity detection |
| Skin Temperature | Thermistor | Degrees C | Continuous monitoring |
| SpO2 | Pulse oximetry | Blood oxygen % | Via red/IR LED ratio |

## Standard BLE Heart Rate (0x2A37)

This is immediately available without protocol RE.

### Format
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
- **HRV (RMSSD)**: Computed from successive RR interval differences
- **Resting HR**: Minimum HR during sleep periods

## Proprietary Data Packets

### Packet Structure
All proprietary data follows the Whoop packet format:
```
[0xAA] [Length: 2B LE] [Cmd + Payload] [Checksum: 4B]
```

### Heart Rate (Proprietary)
- **Command IDs**: 0x23, 0x24, 0x25 (suspected)
- **Payload**: Command byte + HR value + optional RR intervals
- **Encoding**: HR as uint8 (bpm), RR as uint16 LE (ms)
- **Status**: Needs validation

### Accelerometer
- **Command IDs**: 0x30, 0x31, 0x32 (suspected)
- **Payload**: Packed int16 LE samples, 3 axes (x, y, z)
- **Scale**: ~1/2048 to convert raw int16 to g
- **Sample rate**: Unknown, likely 25-50 Hz
- **Status**: Needs validation

### Skin Temperature
- **Command IDs**: 0x40, 0x41 (suspected)
- **Payload**: Temperature value after command byte
- **Encoding candidates**:
  - uint16 LE in hundredths of C (e.g., 3650 = 36.50 C)
  - int16 LE in tenths of C (e.g., 365 = 36.5 C)
  - uint8 direct Celsius
- **Status**: Needs validation

### SpO2
- **Command IDs**: 0x50, 0x51 (suspected)
- **Payload**: SpO2 percentage + optional confidence
- **Encoding candidates**:
  - uint8 direct percentage (e.g., 98 = 98%)
  - uint16 LE in tenths (e.g., 980 = 98.0%)
- **Status**: Needs validation

## Analysis Notes

### Cross-Referencing Strategy
1. Capture standard BLE HR data alongside proprietary packets
2. Match timestamps to identify which proprietary packets contain HR
3. Use HR as ground truth to calibrate proprietary packet parsing
4. Extend to other sensors once HR decoding is confirmed

### Checksum
The 4-byte checksum at the end of each packet is not yet reversed.
This is the biggest open problem for sending custom commands.
Known full packets (with valid checksums) can be replayed.
