#!/usr/bin/env python3
"""Collect serial numbers from network devices using Netmiko.

Inventory file format (YAML):

- device_type: cisco_ios
  host: 192.0.2.10
  username: admin
  password: password
  secret: enablepw  # optional
  serial_command: show inventory  # optional override per device
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Iterable

import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import NetMikoTimeoutException, NetMikoAuthenticationException

SERIAL_PATTERNS = [
    re.compile(r"(?:SN|Serial Number|System Serial Number)\s*[:#]?\s*(\S+)", re.IGNORECASE),
]


def parse_serials(output: str) -> list[str]:
    serials: list[str] = []
    for line in output.splitlines():
        for pattern in SERIAL_PATTERNS:
            match = pattern.search(line)
            if match:
                serials.append(match.group(1))
    return sorted(set(serials))


def load_inventory(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, list):
        raise ValueError("Inventory file must contain a list of device entries")
    return data


def collect_serials(device: dict, command: str) -> list[str]:
    connection = ConnectHandler(**device)
    try:
        if device.get("secret"):
            connection.enable()
        output = connection.send_command(command)
        return parse_serials(output)
    finally:
        connection.disconnect()


def write_csv(rows: Iterable[dict], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["host", "device_type", "serials"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect serial numbers from network devices using Netmiko.",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        required=True,
        help="Path to YAML inventory file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("serial_numbers.csv"),
        help="Path to CSV output file.",
    )
    parser.add_argument(
        "--command",
        default="show inventory",
        help="Command to run for serial retrieval (default: show inventory).",
    )

    args = parser.parse_args()

    try:
        devices = load_inventory(args.inventory)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Failed to load inventory: {exc}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    for device in devices:
        host = device.get("host", "unknown")
        device_type = device.get("device_type", "unknown")
        command = device.get("serial_command", args.command)
        try:
            serials = collect_serials(device, command)
        except (NetMikoTimeoutException, NetMikoAuthenticationException) as exc:
            print(f"Connection failed for {host}: {exc}", file=sys.stderr)
            serials = []
        except Exception as exc:  # noqa: BLE001 - surface unexpected Netmiko errors
            print(f"Error collecting serials from {host}: {exc}", file=sys.stderr)
            serials = []

        rows.append(
            {
                "host": host,
                "device_type": device_type,
                "serials": ";".join(serials),
            }
        )

    try:
        write_csv(rows, args.output)
    except OSError as exc:
        print(f"Failed to write output: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote serial numbers to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
