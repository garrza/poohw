"""Live heart-rate (and optional IMU) streaming via the Whoop proprietary protocol.

Instead of the standard BLE Heart Rate Service (0x2A37), this module uses the
Whoop's proprietary REALTIME_DATA (0x28) packets, which are enabled by sending
TOGGLE_REALTIME_HR (0x03).  This matches the same path used by `capture` +
`replay` and produces validated HR / RR / HRV data from the WG50.

The standard BLE HR parser (`parse_heart_rate`) is kept as a utility for
other consumers that receive data through the standard 0x2A37 characteristic.
"""

import asyncio
import struct
import sys
from datetime import datetime, timezone

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from poohw.decoders.hr import HeartRateDecoder
from poohw.decoders.accel import AccelDecoder
from poohw.decoders.packet import PacketDecoder
from poohw.protocol import (
    PacketType,
    build_packet,
    build_toggle_realtime_hr,
    build_toggle_imu,
    is_proprietary_uuid,
)
from poohw.scanner import find_whoop

# Standard BLE UUIDs (kept for reference / external consumers)
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


# ---------------------------------------------------------------------------
# Standard BLE Heart Rate Measurement parser (0x2A37)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Proprietary protocol streaming
# ---------------------------------------------------------------------------


def _find_write_char(client: BleakClient) -> str | None:
    """Find the CMD_TO_STRAP writable characteristic."""
    for service in client.services:
        if is_proprietary_uuid(service.uuid):
            for char in service.characteristics:
                if "write" in char.properties or "write-without-response" in char.properties:
                    return char.uuid
    return None


async def stream_heart_rate(
    address: str | None = None,
    enable_imu: bool = False,
) -> None:
    """Connect to a Whoop and stream live heart rate (and optionally IMU) data.

    Uses the proprietary protocol:
      1. Subscribe to all proprietary notify characteristics.
      2. Send TOGGLE_REALTIME_HR to enable HR streaming.
      3. (Optionally) Send TOGGLE_IMU_MODE to enable accelerometer.
      4. Decode incoming REALTIME_DATA / REALTIME_IMU_DATA packets live.
      5. On exit, disable the streams and disconnect.
    """
    if address is None:
        device = await find_whoop()
        if device is None:
            print("No Whoop found.")
            return
        address = device.address

    print(f"Connecting to {address}...")

    async with BleakClient(address) as client:
        print(f"Connected. MTU={client.mtu_size}")

        write_uuid = _find_write_char(client)
        if write_uuid is None:
            print("Error: no writable proprietary characteristic found.")
            return

        packet_count = 0

        def _on_notification(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            nonlocal packet_count
            packet = PacketDecoder.decode(data)
            if packet is None:
                return

            now = datetime.now(timezone.utc).strftime("%H:%M:%S")

            # --- Heart rate ---
            if HeartRateDecoder.can_decode(packet):
                hr = HeartRateDecoder.decode(packet)
                if hr is not None:
                    packet_count += 1
                    line = f"[{now}] HR: {hr.hr_bpm} bpm ({hr.hr_precise:.1f})"
                    if hr.rr_intervals_ms:
                        rr_str = ", ".join(f"{v:.0f}" for v in hr.rr_intervals_ms)
                        line += f"  RR: [{rr_str}] ms"
                    if hr.hrv_rmssd_ms is not None:
                        line += f"  HRV(RMSSD): {hr.hrv_rmssd_ms:.1f} ms"
                    if not hr.wearing:
                        line += "  [NOT WEARING]"
                    print(line, flush=True)
                    return

            # --- Accelerometer ---
            if AccelDecoder.can_decode(packet):
                accel = AccelDecoder.decode(packet)
                if accel is not None:
                    packet_count += 1
                    for s in accel.samples:
                        print(
                            f"[{now}] IMU: x={s.x:+.3f}g  y={s.y:+.3f}g  z={s.z:+.3f}g  "
                            f"mag={s.magnitude:.3f}g",
                            flush=True,
                        )
                    return

        # Subscribe to all proprietary notify characteristics
        notify_uuids: list[str] = []
        for service in client.services:
            if is_proprietary_uuid(service.uuid):
                for char in service.characteristics:
                    if "notify" in char.properties:
                        try:
                            await client.start_notify(char, _on_notification)
                            notify_uuids.append(char.uuid)
                        except Exception as e:
                            print(f"  Warning: failed to subscribe {char.uuid}: {e}")

        if not notify_uuids:
            print("Error: no notify characteristics found on proprietary service.")
            return

        print(f"Subscribed to {len(notify_uuids)} characteristic(s).")

        # Enable realtime HR
        print("Enabling realtime HR...")
        await client.write_gatt_char(write_uuid, build_toggle_realtime_hr(True))
        await asyncio.sleep(0.3)

        # Optionally enable IMU
        if enable_imu:
            print("Enabling realtime IMU...")
            await client.write_gatt_char(write_uuid, build_toggle_imu(True))
            await asyncio.sleep(0.3)

        streams = "HR" + (" + IMU" if enable_imu else "")
        print(f"\nStreaming {streams} (Ctrl+C to stop):\n")

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            # Disable streams before disconnecting
            print(f"\n  Disabling streams ({packet_count} packets received)...")
            try:
                await client.write_gatt_char(write_uuid, build_toggle_realtime_hr(False))
                if enable_imu:
                    await client.write_gatt_char(write_uuid, build_toggle_imu(False))
            except Exception:
                pass  # best-effort cleanup


def main() -> None:
    address = sys.argv[1] if len(sys.argv) > 1 else None
    imu = "--imu" in sys.argv
    try:
        asyncio.run(stream_heart_rate(address, enable_imu=imu))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
