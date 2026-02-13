"""Send commands to the Whoop and capture responses."""

import asyncio
import sys
from datetime import datetime, timezone

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from poohw.protocol import (
    Command,
    PacketType,
    build_packet,
    build_toggle_realtime_hr,
    build_toggle_imu,
    build_toggle_imu_historical,
    build_get_data_range,
    build_set_read_pointer,
    build_send_historical_data,
    build_abort_historical,
    build_get_battery,
    build_get_hello,
    format_packet,
    hex_to_bytes,
)
from poohw.ble import dump_services, find_notify_chars, find_write_char
from poohw.scanner import find_whoop


async def request_historical_data(client: BleakClient) -> bool:
    """Run the full historical data workflow so the band streams 0x5C/accel packets.

    Protocol order (per docs): GET_DATA_RANGE → SET_READ_POINTER → SEND_HISTORICAL_DATA.
    Without the first two steps many bands never start streaming.
    """
    write_uuid = find_write_char(client)
    if write_uuid is None:
        return False

    # 1) Query what range the strap has buffered
    await client.write_gatt_char(write_uuid, build_get_data_range())
    await asyncio.sleep(1.2)

    # 2) Position read cursor at start (0 = beginning; band may use range from step 1 internally)
    await client.write_gatt_char(write_uuid, build_set_read_pointer(0))
    await asyncio.sleep(0.3)

    # 3) Start streaming historical records (HISTORICAL_DATA on DATA_FROM_STRAP)
    await client.write_gatt_char(write_uuid, build_send_historical_data())
    return True


async def send_command(
    client: BleakClient,
    cmd_hex: str,
    response_timeout: float = 5.0,
) -> list[dict]:
    """Send a hex command to CMD_TO_STRAP and collect responses."""
    responses: list[dict] = []
    cmd_bytes = hex_to_bytes(cmd_hex)

    write_uuid = find_write_char(client)
    if write_uuid is None:
        print("  Error: No writable characteristic found on the Whoop.")
        dump_services(client)
        return responses

    def make_handler(name: str):
        def handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            now = datetime.now(timezone.utc).isoformat()
            responses.append(
                {
                    "timestamp": now,
                    "uuid": name,
                    "data": bytes(data),
                    "hex": data.hex(),
                    "formatted": format_packet(data),
                }
            )

        return handler

    notify_chars = find_notify_chars(client)
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

    write_uuid = find_write_char(client)
    if write_uuid is None:
        print("  Error: No writable characteristic found on the Whoop.")
        dump_services(client)
        return responses

    def make_handler(name: str):
        def handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            now = datetime.now(timezone.utc).isoformat()
            responses.append(
                {
                    "timestamp": now,
                    "uuid": name,
                    "data": bytes(data),
                    "hex": data.hex(),
                    "formatted": format_packet(data),
                }
            )

        return handler

    notify_chars = find_notify_chars(client)
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


async def _send_to_one(address: str, cmd: int, data: bytes, label: str) -> None:
    """Connect to one Whoop and send a command."""
    print(f"[{address[:8]}...] Connecting...")
    try:
        async with BleakClient(address) as client:
            print(f"[{address[:8]}...] Connected. Sending {label}...")
            await send_built_command(client, cmd, data, response_timeout=3.0)
            print(f"[{address[:8]}...] Done.")
    except Exception as e:
        print(f"[{address[:8]}...] Error: {e}")


async def _get_addresses(address: str | None, all_devices: bool) -> list[str]:
    """Resolve target addresses from flags."""
    if address:
        return [address]
    if all_devices:
        from poohw.scanner import scan

        results = await scan()
        if not results:
            print("No Whoop devices found.")
            return []
        return [dev.address for dev, _ in results]
    else:
        device = await find_whoop()
        if device is None:
            print("No Whoop found.")
            return []
        return [device.address]


async def vibrate(
    address: str | None = None,
    mode: str = "haptics",
    all_devices: bool = False,
) -> None:
    """Make Whoop(s) vibrate."""
    addresses = await _get_addresses(address, all_devices)
    if not addresses:
        return

    cmd = Command.RUN_HAPTICS_PATTERN if mode == "haptics" else Command.RUN_ALARM
    label = Command(cmd).name

    if len(addresses) == 1:
        await _send_to_one(addresses[0], cmd, b"\x00", label)
    else:
        print(f"\nSending {label} to {len(addresses)} devices in parallel...\n")
        await asyncio.gather(
            *[_send_to_one(addr, cmd, b"\x00", label) for addr in addresses]
        )


async def stop_haptics(
    address: str | None = None,
    all_devices: bool = False,
) -> None:
    """Stop haptic vibration on Whoop(s)."""
    addresses = await _get_addresses(address, all_devices)
    if not addresses:
        return

    if len(addresses) == 1:
        await _send_to_one(addresses[0], Command.STOP_HAPTICS, b"\x00", "STOP_HAPTICS")
    else:
        print(f"\nSending STOP_HAPTICS to {len(addresses)} devices in parallel...\n")
        await asyncio.gather(
            *[
                _send_to_one(addr, Command.STOP_HAPTICS, b"\x00", "STOP_HAPTICS")
                for addr in addresses
            ]
        )


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

        write_uuid = find_write_char(client)
        if write_uuid is None:
            print("No writable characteristic found.")
            dump_services(client)
            return

        print(f"Write characteristic: {write_uuid}")

        def make_handler(name: str):
            def handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
                now = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
                print(f"  <- {name} [{now}] {format_packet(data)}")

            return handler

        notify_chars = find_notify_chars(client)
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
        print("    imu on/off         — toggle realtime accelerometer (IMU)")
        print("    imu-hist on/off    — toggle historical IMU batches")
        print("    data-range         — query buffered data range")
        print("    history            — request historical data download")
        print("    history-abort      — abort historical data transmit")
        print("    services           — list all services")
        print("  Or type raw hex to send directly.")
        print("  'q' = quit\n")

        # Shortcuts that use pre-built command packets (not just cmd+data pairs)
        prebuilt_shortcuts: dict[str, bytes] = {
            "imu on": build_toggle_imu(True),
            "imu off": build_toggle_imu(False),
            "imu-hist on": build_toggle_imu_historical(True),
            "imu-hist off": build_toggle_imu_historical(False),
            "data-range": build_get_data_range(),
            "history": build_send_historical_data(),
            "history-abort": build_abort_historical(),
        }

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
                dump_services(client)
                continue

            if user_input.lower() in prebuilt_shortcuts:
                pkt = prebuilt_shortcuts[user_input.lower()]
                print(f"  -> {user_input}: {pkt.hex()}")
                await client.write_gatt_char(write_uuid, pkt)
                await asyncio.sleep(3)
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
                    print(
                        f"  -> Sending raw: {cmd_bytes.hex()} ({len(cmd_bytes)} bytes)"
                    )
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
