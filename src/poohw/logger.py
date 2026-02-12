"""Subscribe to all notification-capable characteristics and log raw packets."""

import asyncio
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from poohw.scanner import find_whoop

LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


async def capture(
    address: str | None = None,
    duration: float | None = None,
    output: str | None = None,
) -> None:
    """Subscribe to all notify characteristics and log raw packets.

    Args:
        address: BLE address. If None, scans for a Whoop.
        duration: Capture duration in seconds. None = run until Ctrl+C.
        output: Output file path. If None, auto-generates in logs/.
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

        print(f"\nCapturing from {len(notify_chars)} characteristics → {outpath}")
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
