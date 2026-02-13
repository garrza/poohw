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
@click.option("--analyze", is_flag=True, help="Pipe decoded packets through the analytics engine.")
@click.option("--max-hr", default=190.0, help="Max HR for analytics (used with --analyze).")
def replay(file: str, output: str | None, verbose: bool, analyze: bool, max_hr: float) -> None:
    """Replay and decode a captured packet log."""
    from poohw.replay import replay_file

    records = replay_file(file, output, verbose)

    if analyze:
        from poohw.analytics.pipeline import run_pipeline

        summary = run_pipeline(records, max_hr=max_hr)
        click.echo(f"\n--- Analytics Summary ---")
        click.echo(summary.to_json())


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


@main.command("vibrate")
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
@click.option("--mode", "-m", type=click.Choice(["haptics", "alarm"]), default="haptics",
              help="Vibration mode: haptics pattern or alarm.")
@click.option("--all", "all_devices", is_flag=True, help="Send to all discovered Whoops.")
def vibrate_cmd(address: str | None, mode: str, all_devices: bool) -> None:
    """Make Whoop(s) vibrate."""
    from poohw.commander import vibrate

    asyncio.run(vibrate(address, mode, all_devices))


@main.command("stop-haptics")
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
@click.option("--all", "all_devices", is_flag=True, help="Send to all discovered Whoops.")
def stop_haptics_cmd(address: str | None, all_devices: bool) -> None:
    """Stop any ongoing haptic vibration."""
    from poohw.commander import stop_haptics

    asyncio.run(stop_haptics(address, all_devices))


@main.command("history")
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
@click.option("--timeout", "-t", default=30.0, help="Response wait timeout in seconds.")
def history_cmd(address: str | None, timeout: float) -> None:
    """Request historical data download from the Whoop."""
    from poohw.commander import send_built_command
    from poohw.protocol import Command
    from poohw.scanner import find_whoop
    from bleak import BleakClient

    async def _history() -> None:
        addr = address
        if addr is None:
            device = await find_whoop()
            if device is None:
                click.echo("No Whoop found.")
                return
            addr = device.address

        click.echo(f"Connecting to {addr}...")
        async with BleakClient(addr) as client:
            click.echo("Requesting historical data...")
            responses = await send_built_command(
                client, Command.SEND_HISTORICAL_DATA, b"", timeout
            )
            if not responses:
                click.echo("No responses received.")
            else:
                click.echo(f"\n{len(responses)} response(s) received.")
                for r in responses:
                    click.echo(f"  [{r['timestamp']}] {r['formatted']}")

    asyncio.run(_history())


@main.command("imu")
@click.argument("state", type=click.Choice(["on", "off"]))
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
@click.option("--historical", "-H", is_flag=True, help="Toggle historical IMU mode instead of realtime.")
def imu_cmd(state: str, address: str | None, historical: bool) -> None:
    """Toggle accelerometer (IMU) streaming on/off."""
    from poohw.commander import send_built_command
    from poohw.protocol import Command
    from poohw.scanner import find_whoop
    from bleak import BleakClient

    enable = state == "on"
    cmd = Command.TOGGLE_IMU_MODE_HISTORICAL if historical else Command.TOGGLE_IMU_MODE
    label = "historical IMU" if historical else "realtime IMU"

    async def _imu() -> None:
        addr = address
        if addr is None:
            device = await find_whoop()
            if device is None:
                click.echo("No Whoop found.")
                return
            addr = device.address

        click.echo(f"Connecting to {addr}...")
        async with BleakClient(addr) as client:
            click.echo(f"Toggling {label} {'ON' if enable else 'OFF'}...")
            responses = await send_built_command(
                client, cmd, b"\x01" if enable else b"\x00", 5.0
            )
            if responses:
                click.echo(f"{len(responses)} response(s):")
                for r in responses:
                    click.echo(f"  {r['formatted']}")

    asyncio.run(_imu())


@main.command("analyze")
@click.argument("file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Write summary JSON to file.")
@click.option("--max-hr", default=190.0, help="Estimated max heart rate.")
@click.option("--sleep-need", default=450.0, help="Sleep need in minutes (default 7.5h).")
def analyze_cmd(file: str, output: str | None, max_hr: float, sleep_need: float) -> None:
    """Run the full analytics pipeline on a captured packet log."""
    from poohw.replay import replay_file
    from poohw.analytics.pipeline import run_pipeline

    # Replay the capture to get decoded records
    records = replay_file(file, verbose=False)

    summary = run_pipeline(
        records,
        max_hr=max_hr,
        sleep_need_min=sleep_need,
    )

    click.echo(f"\n{'=' * 60}")
    click.echo(f"  Daily Summary: {summary.date}")
    click.echo(f"{'=' * 60}")
    click.echo(f"  Sleep:      {summary.sleep_total_min:.0f} min "
               f"(eff {summary.sleep_efficiency:.0%})")
    click.echo(f"  Recovery:   {summary.recovery_score:.0f}/100")
    click.echo(f"  HRV:        {summary.hrv_rmssd_ms:.1f} ms "
               f"(score {summary.hrv_score:.1f})")
    click.echo(f"  Resting HR: {summary.resting_hr:.0f} bpm")
    click.echo(f"  Strain:     {summary.strain_score:.1f}/21")
    click.echo(f"  SpO2:       {summary.spo2_median:.0f}% "
               f"(min {summary.spo2_min:.0f}%)")
    click.echo(f"  Resp rate:  {summary.respiratory_rate:.1f} breaths/min")
    if summary.skin_temp_c is not None:
        click.echo(f"  Skin temp:  {summary.skin_temp_c:.1f} °C")
    click.echo(f"  Calories:   {summary.calories:.0f}")
    click.echo(f"{'=' * 60}")

    if output:
        with open(output, "w") as f:
            f.write(summary.to_json())
        click.echo(f"\nSummary written to {output}")


@main.command("data-range")
@click.option("--address", "-a", default=None, help="BLE address to connect to.")
def data_range_cmd(address: str | None) -> None:
    """Query what historical data range is buffered on the Whoop."""
    from poohw.commander import send_built_command
    from poohw.protocol import Command
    from poohw.scanner import find_whoop
    from bleak import BleakClient

    async def _data_range() -> None:
        addr = address
        if addr is None:
            device = await find_whoop()
            if device is None:
                click.echo("No Whoop found.")
                return
            addr = device.address

        click.echo(f"Connecting to {addr}...")
        async with BleakClient(addr) as client:
            click.echo("Querying data range...")
            responses = await send_built_command(
                client, Command.GET_DATA_RANGE, b"", 5.0
            )
            if not responses:
                click.echo("No response.")
            else:
                for r in responses:
                    click.echo(f"  {r['formatted']}")
                    click.echo(f"  raw: {r['hex']}")

    asyncio.run(_data_range())


if __name__ == "__main__":
    main()
