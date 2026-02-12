"""Connect to a Whoop and enumerate all BLE services, characteristics, and descriptors."""

import asyncio
import sys

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from poohw.scanner import find_whoop


def _props_str(char: BleakGATTCharacteristic) -> str:
    """Format characteristic properties as a readable string."""
    return ", ".join(sorted(char.properties))


async def discover(address: str | None = None, dump_path: str | None = None) -> str:
    """Connect to a Whoop and dump all BLE services/characteristics/descriptors.

    Args:
        address: BLE address to connect to. If None, scans for a Whoop.
        dump_path: If provided, write the dump to this file path.

    Returns:
        The full discovery dump as a string.
    """
    if address is None:
        print("No address provided, scanning for Whoop...")
        device = await find_whoop()
        if device is None:
            print("No Whoop found. Make sure it's nearby and not connected to another device.")
            return ""
        address = device.address
        print(f"Using device at {address}\n")

    lines: list[str] = []

    def log(msg: str = "") -> None:
        lines.append(msg)
        print(msg)

    async with BleakClient(address) as client:
        log(f"Connected to {address}")
        log(f"MTU: {client.mtu_size}")
        log()

        for service in client.services:
            log(f"Service: {service.uuid}")
            log(f"  Description: {service.description}")
            log(f"  Handle: 0x{service.handle:04X}")
            log()

            for char in service.characteristics:
                log(f"  Characteristic: {char.uuid}")
                log(f"    Description: {char.description}")
                log(f"    Handle: 0x{char.handle:04X}")
                log(f"    Properties: {_props_str(char)}")

                # Try to read readable characteristics
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char)
                        log(f"    Value (hex): {value.hex()}")
                        # Try UTF-8 decode for string-like values
                        try:
                            text = value.decode("utf-8")
                            if text.isprintable():
                                log(f"    Value (str): {text}")
                        except (UnicodeDecodeError, ValueError):
                            pass
                    except Exception as e:
                        log(f"    Read error: {e}")

                for desc in char.descriptors:
                    log(f"    Descriptor: {desc.uuid}")
                    log(f"      Handle: 0x{desc.handle:04X}")
                    try:
                        value = await client.read_gatt_descriptor(desc.handle)
                        log(f"      Value (hex): {value.hex()}")
                    except Exception as e:
                        log(f"      Read error: {e}")

                log()

    dump = "\n".join(lines)
    if dump_path:
        with open(dump_path, "w") as f:
            f.write(dump)
        print(f"\nDump saved to {dump_path}")

    return dump


def main() -> None:
    address = sys.argv[1] if len(sys.argv) > 1 else None
    dump_path = sys.argv[2] if len(sys.argv) > 2 else "docs/ble_services.md"
    asyncio.run(discover(address, dump_path))


if __name__ == "__main__":
    main()
