"""Scan for Whoop BLE devices."""

import asyncio

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

WHOOP_NAME_PREFIX = "WHOOP"


async def scan(timeout: float = 10.0) -> list[tuple[BLEDevice, AdvertisementData]]:
    """Scan for nearby Whoop devices.

    Returns a list of (device, advertisement_data) tuples for devices
    whose name starts with 'WHOOP'.
    """
    results: list[tuple[BLEDevice, AdvertisementData]] = []

    def _callback(device: BLEDevice, adv: AdvertisementData) -> None:
        name = adv.local_name or device.name or ""
        if name.upper().startswith(WHOOP_NAME_PREFIX):
            # Avoid duplicates
            if not any(d.address == device.address for d, _ in results):
                results.append((device, adv))
                print(f"  Found: {name} [{device.address}] RSSI={adv.rssi} dBm")
                if adv.service_uuids:
                    print(f"    Service UUIDs: {adv.service_uuids}")
                if adv.manufacturer_data:
                    for mid, data in adv.manufacturer_data.items():
                        print(f"    Manufacturer 0x{mid:04X}: {data.hex()}")

    scanner = BleakScanner(detection_callback=_callback)
    print(f"Scanning for Whoop devices ({timeout}s)...")
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()

    if not results:
        print("No Whoop devices found.")
    else:
        print(f"\n{len(results)} Whoop device(s) found.")

    return results


async def find_whoop(timeout: float = 10.0) -> BLEDevice | None:
    """Find the first Whoop device and return it."""
    results = await scan(timeout)
    if results:
        return results[0][0]
    return None


def main() -> None:
    asyncio.run(scan())


if __name__ == "__main__":
    main()
