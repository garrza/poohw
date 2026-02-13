"""Send commands to the Whoop and capture responses."""

import asyncio
import sys
from datetime import datetime, timezone

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from poohw.protocol import (
    CMD_FROM_STRAP_UUID,
    CMD_TO_STRAP_UUID,
    DATA_FROM_STRAP_UUID,
    EVENTS_FROM_STRAP_UUID,
    WHOOP_SERVICE_UUID,
    Command,
    PacketType,
    build_packet,
    format_packet,
    hex_to_bytes,
)
from poohw.scanner import find_whoop


def _find_char_by_uuid(client: BleakClient, uuid: str):
    """Find a characteristic by UUID, returning None if not found."""
    for service in client.services:
        for char in service.characteristics:
            if char.uuid == uuid:
                return char
    return None


def _dump_services(client: BleakClient) -> None:
    """Print all discovered services and characteristics."""
    print("\n  Available services/characteristics:")
    for service in client.services:
        print(f"    Service: {service.uuid} [{service.description}]")
        for char in service.characteristics:
            props = ", ".join(sorted(char.properties))
            print(f"      {char.uuid} [{props}]")


def _find_write_char(client: BleakClient) -> str | None:
    """Find the writable characteristic on the Whoop proprietary service.

    Tries the known CMD_TO_STRAP UUID first, then falls back to searching
    for any writable characteristic under a 61080xxx service.
    """
    # Try exact match first
    char = _find_char_by_uuid(client, CMD_TO_STRAP_UUID)
    if char and ("write" in char.properties or "write-without-response" in char.properties):
        return char.uuid

    # Fall back: search for writable chars in 610800xx services
    for service in client.services:
        if service.uuid.startswith("61080"):
            for char in service.characteristics:
                if "write" in char.properties or "write-without-response" in char.properties:
                    print(f"  Using writable characteristic: {char.uuid}")
                    return char.uuid

    return None


def _find_notify_chars(client: BleakClient) -> list[tuple[str, str]]:
    """Find all notify-capable characteristics on 610800xx services.

    Returns list of (uuid, friendly_name) tuples.
    """
    known = {
        CMD_FROM_STRAP_UUID: "CMD_FROM_STRAP",
        EVENTS_FROM_STRAP_UUID: "EVENTS_FROM_STRAP",
        DATA_FROM_STRAP_UUID: "DATA_FROM_STRAP",
    }
    result: list[tuple[str, str]] = []

    # Try known UUIDs first
    for uuid, name in known.items():
        char = _find_char_by_uuid(client, uuid)
        if char and "notify" in char.properties:
            result.append((uuid, name))

    # Also pick up any other notify chars on 610800xx services
    for service in client.services:
        if service.uuid.startswith("61080"):
            for char in service.characteristics:
                if "notify" in char.properties and char.uuid not in known:
                    result.append((char.uuid, char.uuid[:12] + "..."))

    return result


async def send_command(
    client: BleakClient,
    cmd_hex: str,
    response_timeout: float = 5.0,
) -> list[dict]:
    """Send a hex command to CMD_TO_STRAP and collect responses."""
    responses: list[dict] = []
    cmd_bytes = hex_to_bytes(cmd_hex)

    write_uuid = _find_write_char(client)
    if write_uuid is None:
        print("  Error: No writable characteristic found on the Whoop.")
        _dump_services(client)
        return responses

    def make_handler(name: str):
        def handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            now = datetime.now(timezone.utc).isoformat()
            responses.append({
                "timestamp": now,
                "uuid": name,
                "data": bytes(data),
                "hex": data.hex(),
                "formatted": format_packet(data),
            })
        return handler

    notify_chars = _find_notify_chars(client)
    for uuid, name in notify_chars:
        try:
            await client.start_notify(uuid, make_handler(name))
        except Exception:
            pass

    await asyncio.sleep(0.2)
    await client.write_gatt_char(write_uuid, cmd_bytes)
    await asyncio.sleep(response_timeout)

    for uuid, _ in notify_chars:
        try:
            await client.stop_notify(uuid)
        except Exception:
            pass

    return responses


async def send_built_command(
    client: BleakClient,
    command: int,
    data: bytes = b"",
    response_timeout: float = 5.0,
) -> list[dict]:
    """Build and send a command using the proper packet framing."""
    pkt = build_packet(PacketType.COMMAND, command, data)
    responses: list[dict] = []

    write_uuid = _find_write_char(client)
    if write_uuid is None:
        print("  Error: No writable characteristic found on the Whoop.")
        _dump_services(client)
        return responses

    def make_handler(name: str):
        def handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            now = datetime.now(timezone.utc).isoformat()
            responses.append({
                "timestamp": now,
                "uuid": name,
                "data": bytes(data),
                "hex": data.hex(),
                "formatted": format_packet(data),
            })
        return handler

    notify_chars = _find_notify_chars(client)
    for uuid, name in notify_chars:
        try:
            await client.start_notify(uuid, make_handler(name))
        except Exception:
            pass

    await asyncio.sleep(0.2)
    print(f"  -> Sending: {pkt.hex()} ({len(pkt)} bytes)")
    await client.write_gatt_char(write_uuid, pkt)
    await asyncio.sleep(response_timeout)

    for uuid, _ in notify_chars:
        try:
            await client.stop_notify(uuid)
        except Exception:
            pass

    return responses


async def vibrate(address: str | None = None, mode: str = "haptics") -> None:
    """Make the Whoop vibrate."""
    if address is None:
        device = await find_whoop()
        if device is None:
            print("No Whoop found.")
            return
        address = device.address

    cmd = Command.RUN_HAPTICS_PATTERN if mode == "haptics" else Command.RUN_ALARM
    print(f"Connecting to {address}...")

    async with BleakClient(address) as client:
        print(f"Connected. Sending {Command(cmd).name}...")
        responses = await send_built_command(client, cmd, b"\x00")

        if responses:
            print(f"\n{len(responses)} response(s):")
            for r in responses:
                print(f"  [{r['timestamp']}] {r['uuid']}: {r['formatted']}")
        else:
            print("No response (command may have still worked).")


async def stop_haptics(address: str | None = None) -> None:
    """Stop any ongoing haptic vibration."""
    if address is None:
        device = await find_whoop()
        if device is None:
            print("No Whoop found.")
            return
        address = device.address

    print(f"Connecting to {address}...")
    async with BleakClient(address) as client:
        print("Connected. Sending STOP_HAPTICS...")
        responses = await send_built_command(client, Command.STOP_HAPTICS, b"\x00")
        if responses:
            for r in responses:
                print(f"  {r['uuid']}: {r['formatted']}")
        else:
            print("No response.")


async def interactive_repl(address: str | None = None) -> None:
    """Interactive REPL for sending commands to the Whoop."""
    if address is None:
        device = await find_whoop()
        if device is None:
            print("No Whoop found.")
            return
        address = device.address

    print(f"Connecting to {address}...")

    async with BleakClient(address) as client:
        print("Connected.\n")

        write_uuid = _find_write_char(client)
        if write_uuid is None:
            print("No writable characteristic found.")
            _dump_services(client)
            return

        print(f"Write characteristic: {write_uuid}")

        def make_handler(name: str):
            def handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
                now = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
                print(f"  <- {name} [{now}] {format_packet(data)}")
            return handler

        notify_chars = _find_notify_chars(client)
        for uuid, name in notify_chars:
            try:
                await client.start_notify(uuid, make_handler(name))
                print(f"Subscribed: {name} ({uuid})")
            except Exception as e:
                print(f"Failed to subscribe {name}: {e}")

        if not notify_chars:
            print("Warning: No notify characteristics found.")

        print("\nWhoop Commander REPL")
        print("  Shortcuts:")
        print("    vibrate / haptics  — trigger haptic vibration")
        print("    alarm              — trigger alarm vibration")
        print("    stop               — stop haptics")
        print("    battery            — get battery level")
        print("    hello              — send GET_HELLO")
        print("    hr on/off          — toggle realtime HR")
        print("    services           — list all services")
        print("  Or type raw hex to send directly.")
        print("  'q' = quit\n")

        shortcuts = {
            "vibrate": (Command.RUN_HAPTICS_PATTERN, b"\x00"),
            "haptics": (Command.RUN_HAPTICS_PATTERN, b"\x00"),
            "alarm": (Command.RUN_ALARM, b"\x00"),
            "stop": (Command.STOP_HAPTICS, b"\x00"),
            "battery": (Command.GET_BATTERY_LEVEL, b""),
            "hello": (Command.GET_HELLO, b""),
            "hr on": (Command.TOGGLE_REALTIME_HR, b"\x01"),
            "hr off": (Command.TOGGLE_REALTIME_HR, b"\x00"),
        }

        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("cmd> ")
                )
            except EOFError:
                break

            user_input = user_input.strip()
            if not user_input:
                continue
            if user_input.lower() in ("q", "quit", "exit"):
                break

            if user_input.lower() == "services":
                _dump_services(client)
                continue

            if user_input.lower() in shortcuts:
                cmd, data = shortcuts[user_input.lower()]
                pkt = build_packet(PacketType.COMMAND, cmd, data)
                print(f"  -> {Command(cmd).name}: {pkt.hex()}")
                await client.write_gatt_char(write_uuid, pkt)
                await asyncio.sleep(3)
            else:
                try:
                    cmd_bytes = hex_to_bytes(user_input)
                    print(f"  -> Sending raw: {cmd_bytes.hex()} ({len(cmd_bytes)} bytes)")
                    await client.write_gatt_char(write_uuid, cmd_bytes)
                    await asyncio.sleep(3)
                except ValueError as e:
                    print(f"  Invalid hex: {e}")
                except Exception as e:
                    print(f"  Error: {e}")

        print("Disconnecting.")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "repl"
    address = sys.argv[2] if len(sys.argv) > 2 else None

    if mode == "vibrate":
        asyncio.run(vibrate(address, "haptics"))
    elif mode == "alarm":
        asyncio.run(vibrate(address, "alarm"))
    elif mode == "stop":
        asyncio.run(stop_haptics(address))
    else:
        asyncio.run(interactive_repl(address))


if __name__ == "__main__":
    main()
