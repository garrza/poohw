"""CLI for the poohw Whoop reverse engineering toolkit."""

import asyncio

import click


@click.group()
def main() -> None:
    """poohw — Whoop 4.0 BLE reverse engineering toolkit."""


@main.command()
@click.option("--timeout", "-t", default=10.0, help="Scan timeout in seconds.")
def scan(timeout: float) -> None:
    """Scan for nearby Whoop BLE devices."""
    from poohw.scanner import scan as do_scan

    asyncio.run(do_scan(timeout))


@main.command()
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
@click.option("--output", "-o", default="docs/ble_services.md", help="Output file path.")
def discover(address: str | None, output: str) -> None:
    """Connect to a Whoop and dump all BLE services/characteristics."""
    from poohw.discovery import discover as do_discover

    asyncio.run(do_discover(address, output))


@main.command()
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
def stream(address: str | None) -> None:
    """Stream live heart rate from a Whoop."""
    from poohw.heart_rate import stream_heart_rate

    try:
        asyncio.run(stream_heart_rate(address))
    except KeyboardInterrupt:
        click.echo("\nStopped.")


@main.command()
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
@click.option("--duration", "-d", default=None, type=float, help="Capture duration in seconds.")
@click.option("--output", "-o", default=None, help="Output file path.")
def capture(address: str | None, duration: float | None, output: str | None) -> None:
    """Capture raw BLE packets from a Whoop to a file."""
    from poohw.logger import capture as do_capture

    try:
        asyncio.run(do_capture(address, duration, output))
    except KeyboardInterrupt:
        click.echo("\nStopped.")


@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output decoded data as JSON.")
@click.option("--verbose", "-v", is_flag=True, help="Show all packets including undecoded.")
def replay(file: str, output: str | None, verbose: bool) -> None:
    """Replay and decode a captured packet log."""
    from poohw.replay import replay_file

    replay_file(file, output, verbose)


@main.command()
@click.argument("hex_cmd")
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
@click.option("--timeout", "-t", default=5.0, help="Response wait timeout in seconds.")
def send(hex_cmd: str, address: str | None, timeout: float) -> None:
    """Send a raw hex command to the Whoop."""
    from poohw.commander import send_command
    from poohw.protocol import hex_to_bytes, format_packet
    from poohw.scanner import find_whoop
    from bleak import BleakClient

    async def _send() -> None:
        addr = address
        if addr is None:
            device = await find_whoop()
            if device is None:
                click.echo("No Whoop found.")
                return
            addr = device.address

        click.echo(f"Connecting to {addr}...")
        async with BleakClient(addr) as client:
            click.echo(f"Sending: {hex_cmd}")
            responses = await send_command(client, hex_cmd, timeout)

            if not responses:
                click.echo("No responses received.")
            else:
                click.echo(f"\n{len(responses)} response(s):")
                for r in responses:
                    click.echo(f"  [{r['timestamp']}] {r['uuid']}")
                    click.echo(f"    {r['formatted']}")
                    click.echo(f"    raw: {r['hex']}")

    asyncio.run(_send())


@main.command()
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
def repl(address: str | None) -> None:
    """Interactive REPL for sending commands to the Whoop."""
    from poohw.commander import interactive_repl

    try:
        asyncio.run(interactive_repl(address))
    except KeyboardInterrupt:
        click.echo("\nStopped.")


if __name__ == "__main__":
    main()
