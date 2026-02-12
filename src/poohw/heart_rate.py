"""Parse standard BLE Heart Rate Measurement (UUID 0x2A37) from the Whoop."""

import asyncio
import struct
import sys
from datetime import datetime, timezone

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from poohw.scanner import find_whoop

# Standard BLE UUIDs
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


def parse_heart_rate(data: bytearray) -> dict:
    """Parse a standard BLE Heart Rate Measurement value.

    Per Bluetooth SIG spec:
    - Byte 0: Flags
      - Bit 0: HR format (0 = uint8, 1 = uint16)
      - Bit 1-2: Sensor contact status
      - Bit 3: Energy expended present
      - Bit 4: RR-interval present
    - Byte 1(+2): Heart rate value
    - Optional: Energy expended (uint16)
    - Optional: RR-intervals (uint16 each, in 1/1024 sec units)
    """
    flags = data[0]
    hr_format_16bit = bool(flags & 0x01)
    sensor_contact_supported = bool(flags & 0x02)
    sensor_contact_detected = bool(flags & 0x04)
    energy_expended_present = bool(flags & 0x08)
    rr_interval_present = bool(flags & 0x10)

    offset = 1

    if hr_format_16bit:
        hr_value = struct.unpack_from("<H", data, offset)[0]
        offset += 2
    else:
        hr_value = data[offset]
        offset += 1

    energy_expended = None
    if energy_expended_present:
        energy_expended = struct.unpack_from("<H", data, offset)[0]
        offset += 2

    rr_intervals: list[float] = []
    if rr_interval_present:
        while offset + 1 < len(data):
            rr_raw = struct.unpack_from("<H", data, offset)[0]
            # Convert from 1/1024 sec to milliseconds
            rr_ms = (rr_raw / 1024.0) * 1000.0
            rr_intervals.append(round(rr_ms, 1))
            offset += 2

    return {
        "hr_bpm": hr_value,
        "sensor_contact": sensor_contact_detected if sensor_contact_supported else None,
        "energy_expended_kj": energy_expended,
        "rr_intervals_ms": rr_intervals,
    }


async def stream_heart_rate(address: str | None = None) -> None:
    """Connect to a Whoop and stream heart rate data."""
    if address is None:
        device = await find_whoop()
        if device is None:
            print("No Whoop found.")
            return
        address = device.address

    print(f"Connecting to {address}...")

    async with BleakClient(address) as client:
        print("Connected. Streaming heart rate (Ctrl+C to stop):\n")

        def hr_handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S")
            parsed = parse_heart_rate(data)
            hr = parsed["hr_bpm"]
            rr = parsed["rr_intervals_ms"]

            line = f"[{now}] HR: {hr} bpm"
            if rr:
                rr_str = ", ".join(f"{v:.0f}" for v in rr)
                # Compute HRV (RMSSD) if we have 2+ RR intervals
                if len(rr) >= 2:
                    diffs = [rr[i + 1] - rr[i] for i in range(len(rr) - 1)]
                    rmssd = (sum(d * d for d in diffs) / len(diffs)) ** 0.5
                    line += f"  RR: [{rr_str}] ms  HRV(RMSSD): {rmssd:.1f} ms"
                else:
                    line += f"  RR: [{rr_str}] ms"
            print(line)

        await client.start_notify(HR_MEASUREMENT_UUID, hr_handler)

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass


def main() -> None:
    address = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        asyncio.run(stream_heart_rate(address))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
