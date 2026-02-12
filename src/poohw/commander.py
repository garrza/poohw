"""Send commands to the Whoop and capture responses."""

import asyncio
import sys
from datetime import datetime, timezone

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from poohw.protocol import (
    CMD_FROM_STRAP_UUID,
    CMD_GET_SENSOR_DATA,
    CMD_TO_STRAP_UUID,
    DATA_FROM_STRAP_UUID,
    format_packet,
    hex_to_bytes,
)
from poohw.scanner import find_whoop


async def send_command(
    client: BleakClient,
    cmd_hex: str,
    response_timeout: float = 5.0,
) -> list[dict]:
    """Send a hex command to CMD_TO_STRAP and collect responses.

    Subscribes to CMD_FROM_STRAP and DATA_FROM_STRAP before sending,
    collects responses for `response_timeout` seconds.

    Returns list of response dicts with uuid, data, hex, timestamp.
    """
    responses: list[dict] = []
    cmd_bytes = hex_to_bytes(cmd_hex)

    def make_handler(uuid: str):
        def handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            now = datetime.now(timezone.utc).isoformat()
            responses.append({
                "timestamp": now,
                "uuid": uuid,
                "data": bytes(data),
                "hex": data.hex(),
                "formatted": format_packet(data),
            })
        return handler

    # Subscribe to response characteristics
    await client.start_notify(CMD_FROM_STRAP_UUID, make_handler("CMD_FROM_STRAP"))
    await client.start_notify(DATA_FROM_STRAP_UUID, make_handler("DATA_FROM_STRAP"))

    # Brief delay to ensure subscriptions are active
    await asyncio.sleep(0.2)

    # Send command
    await client.write_gatt_char(CMD_TO_STRAP_UUID, cmd_bytes)

    # Collect responses
    await asyncio.sleep(response_timeout)

    # Unsubscribe
    try:
        await client.stop_notify(CMD_FROM_STRAP_UUID)
        await client.stop_notify(DATA_FROM_STRAP_UUID)
    except Exception:
        pass

    return responses


async def interactive_repl(address: str | None = None) -> None:
    """Interactive REPL for sending commands to the Whoop.

    Subscribes to CMD_FROM_STRAP and DATA_FROM_STRAP, then lets you type
    hex commands to send. Responses are printed in real time.
    """
    if address is None:
        device = await find_whoop()
        if device is None:
            print("No Whoop found.")
            return
        address = device.address

    print(f"Connecting to {address}...")

    async with BleakClient(address) as client:
        print("Connected.\n")

        def cmd_handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
            print(f"  <- CMD_FROM_STRAP [{now}] {format_packet(data)}")
            print(f"     raw: {data.hex()}")

        def data_handler(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
            print(f"  <- DATA_FROM_STRAP [{now}] len={len(data)} {data.hex()}")

        await client.start_notify(CMD_FROM_STRAP_UUID, cmd_handler)
        await client.start_notify(DATA_FROM_STRAP_UUID, data_handler)
        print("Subscribed to CMD_FROM_STRAP and DATA_FROM_STRAP.\n")

        print("Whoop Commander REPL")
        print("  Type hex to send (e.g., aa0800a8230e16001147c585)")
        print("  'sensor' = send known sensor data command")
        print("  'q' = quit\n")

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

            if user_input.lower() == "sensor":
                user_input = CMD_GET_SENSOR_DATA

            try:
                cmd_bytes = hex_to_bytes(user_input)
                print(f"  -> Sending: {cmd_bytes.hex()} ({len(cmd_bytes)} bytes)")
                await client.write_gatt_char(CMD_TO_STRAP_UUID, cmd_bytes)
                # Wait a bit for responses
                await asyncio.sleep(3)
            except ValueError as e:
                print(f"  Invalid hex: {e}")
            except Exception as e:
                print(f"  Error: {e}")

        print("Disconnecting.")


async def run_known_command(address: str | None = None) -> None:
    """Send the known sensor data command and print responses."""
    if address is None:
        device = await find_whoop()
        if device is None:
            print("No Whoop found.")
            return
        address = device.address

    print(f"Connecting to {address}...")

    async with BleakClient(address) as client:
        print(f"Connected. Sending known sensor data command...\n")
        print(f"  -> {CMD_GET_SENSOR_DATA}")

        responses = await send_command(client, CMD_GET_SENSOR_DATA)

        if not responses:
            print("\nNo responses received.")
        else:
            print(f"\n{len(responses)} response(s):")
            for r in responses:
                src = r["uuid"]
                print(f"  [{r['timestamp']}] {src}")
                print(f"    {r['formatted']}")
                print(f"    raw: {r['hex']}")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "cmd"
    address = sys.argv[2] if len(sys.argv) > 2 else None

    if mode == "repl":
        asyncio.run(interactive_repl(address))
    else:
        asyncio.run(run_known_command(address))


if __name__ == "__main__":
    main()
