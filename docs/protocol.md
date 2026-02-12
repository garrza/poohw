# Whoop 4.0 BLE Protocol Reference

## BLE Services

### Standard Services

| Service | UUID | Notes |
|---------|------|-------|
| Heart Rate | 0x180D | Standard BLE HR profile |
| Device Information | 0x180A | Model, firmware version, etc. |
| Battery | 0x180F | Battery level |

### Proprietary Service

**Service UUID**: `61080001-8d6d-82b8-614a-1c8cb0f8dcc6`

| Characteristic | UUID | Properties | Description |
|----------------|------|------------|-------------|
| CMD_TO_STRAP | `61080002-...` | write | Send commands to device |
| CMD_FROM_STRAP | `61080003-...` | notify | Command responses |
| DATA_FROM_STRAP | `61080004-...` | notify | Sensor/bulk data |

## Packet Format

```
[0xAA] [Length: 2B LE] [Command + Payload] [Checksum: 4B]
```

### Header
- Always `0xAA`

### Length
- 16-bit little-endian
- Size of the command + payload section (excludes header, length field, and checksum)

### Checksum
- 32-bit value
- Algorithm not yet fully reversed
- Appears to be some form of CRC32 or custom hash

## Known Commands

### Get Sensor Data
- **Hex**: `aa 08 00 a8 23 0e 16 00 11 47 c5 85`
- **Parsed**: header=AA, len=8, payload=a8230e160011, checksum=0x85C54711 (TBC)
- **Response**: Returns recent sensor data on DATA_FROM_STRAP

## Command IDs (Partial)

| ID | Direction | Description |
|----|-----------|-------------|
| 0xa8 | to strap | Request sensor data (TBC) |

## Data Formats

### Heart Rate Measurement (Standard BLE 0x2A37)
Standard Bluetooth SIG format:
- Byte 0: Flags (HR format, contact status, energy, RR present)
- Byte 1+: HR value (uint8 or uint16)
- Optional: Energy expended (uint16)
- Optional: RR intervals (uint16 each, units of 1/1024 sec)

### Proprietary Sensor Data
*Format under active investigation. See captured data in `logs/` directory.*

## References

- [jogolden/whoomp](https://github.com/jogolden/whoomp) — Firmware RE
- [bWanShiTong](https://github.com/bWanShiTong) — BLE protocol research
- [Bluetooth SIG Heart Rate Profile](https://www.bluetooth.com/specifications/specs/heart-rate-profile-1-0/)
