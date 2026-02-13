"""Subscribe to all notification-capable characteristics and log raw packets."""

import asyncio
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from poohw.protocol import (
    build_toggle_realtime_hr,
    build_toggle_imu,
    is_proprietary_uuid,
)
from poohw.scanner import find_whoop

LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def _find_write_char(client: BleakClient) -> str | None:
    """Find the CMD_TO_STRAP writable characteristic."""
    for service in client.services:
        if is_proprietary_uuid(service.uuid):
            for char in service.characteristics:
                if "write" in char.properties or "write-without-response" in char.properties:
                    return char.uuid
    return None


async def capture(
    address: str | None = None,
    duration: float | None = None,
    output: str | None = None,
    request_history: bool = False,
    enable_hr: bool = True,
    enable_imu: bool = False,
) -> None:
    """Subscribe to all notify characteristics and log raw packets.

    Args:
        address: BLE address. If None, scans for a Whoop.
        duration: Capture duration in seconds. None = run until Ctrl+C.
        output: Output file path. If None, auto-generates in logs/.
        request_history: If True, send SEND_HISTORICAL_DATA after subscribing
            so the band pushes historical (0x5C, accel, etc.) packets.
        enable_hr: If True, send TOGGLE_REALTIME_HR to start HR streaming.
        enable_imu: If True, send TOGGLE_IMU_MODE to start accelerometer streaming.
    """
    if address is None:
        device = await find_whoop()
        if device is None:
            print("No Whoop found.")
            return
        address = device.address

    if output is None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = str(LOGS_DIR / f"capture_{ts}.jsonl")

    outpath = Path(output)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    print(f"Connecting to {address}...")

    async with BleakClient(address) as client:
        print(f"Connected. MTU={client.mtu_size}")

        f = open(outpath, "a")

        def make_handler(char_uuid: str, char_handle: int):
            def handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
                nonlocal count
                now = datetime.now(timezone.utc).isoformat()
                record = {
                    "timestamp": now,
                    "handle": char_handle,
                    "uuid": char_uuid,
                    "hex_data": data.hex(),
                    "raw_bytes_b64": base64.b64encode(bytes(data)).decode("ascii"),
                    "length": len(data),
                }
                line = json.dumps(record)
                f.write(line + "\n")
                f.flush()
                count += 1
                print(f"  [{now}] 0x{char_handle:04X} ({char_uuid[:8]}...) "
                      f"len={len(data)} {data.hex()}")
            return handler

        # Subscribe to all notify-capable characteristics
        notify_chars = []
        for service in client.services:
            for char in service.characteristics:
                if "notify" in char.properties:
                    try:
                        await client.start_notify(char, make_handler(char.uuid, char.handle))
                        notify_chars.append(char)
                        print(f"Subscribed: {char.uuid} (0x{char.handle:04X}) [{char.description}]")
                    except Exception as e:
                        print(f"Failed to subscribe {char.uuid}: {e}")

        if not notify_chars:
            print("No notify characteristics found.")
            f.close()
            return

        # Enable realtime streams via proprietary commands
        write_uuid = _find_write_char(client)
        if write_uuid and (enable_hr or enable_imu):
            if enable_hr:
                print("Enabling realtime HR streaming...")
                await client.write_gatt_char(write_uuid, build_toggle_realtime_hr(True))
                await asyncio.sleep(0.3)
            if enable_imu:
                print("Enabling realtime IMU streaming...")
                await client.write_gatt_char(write_uuid, build_toggle_imu(True))
                await asyncio.sleep(0.3)
        elif (enable_hr or enable_imu) and write_uuid is None:
            print("Warning: no writable characteristic found; cannot enable HR/IMU streams.")

        if request_history:
            from poohw.commander import request_historical_data
            print("Requesting historical data (GET_DATA_RANGE → SET_READ_POINTER → SEND_HISTORICAL_DATA)...")
            if await request_historical_data(client):
                print("  Full workflow sent. Keep capturing 30–90s for 0x5C/accel packets on DATA_FROM_STRAP.")
            else:
                print("  Could not find write characteristic; skipping request.")
            # Brief pause so the first burst doesn't get lost
            await asyncio.sleep(0.5)

        streams = []
        if enable_hr:
            streams.append("HR")
        if enable_imu:
            streams.append("IMU")
        if request_history:
            streams.append("history")
        stream_label = " + ".join(streams) if streams else "passive"
        print(f"\nCapturing [{stream_label}] from {len(notify_chars)} characteristics → {outpath}")
        print("Press Ctrl+C to stop.\n")

        try:
            if duration:
                await asyncio.sleep(duration)
            else:
                # Run until cancelled
                while True:
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            # Disable streams before disconnecting
            if write_uuid:
                try:
                    if enable_hr:
                        await client.write_gatt_char(write_uuid, build_toggle_realtime_hr(False))
                    if enable_imu:
                        await client.write_gatt_char(write_uuid, build_toggle_imu(False))
                except Exception:
                    pass  # best-effort cleanup
            f.close()
            print(f"\nCapture complete. {count} packets → {outpath}")


def main() -> None:
    address = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        asyncio.run(capture(address))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
