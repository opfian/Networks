#!/usr/bin/env python3
"""Manage Cisco Catalyst devices with Netmiko.

Workflow:
1) Backup running config.
2) Upload IOS image via SCP.
3) Confirm image presence and configure boot system.
4) Push config from backup back onto device.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import pathlib
import sys
from dataclasses import dataclass
from typing import Iterable

from netmiko import ConnectHandler
from netmiko.file_transfer import file_transfer


@dataclass
class DeviceRecord:
    ip: str
    username: str
    password: str
    secret: str | None = None
    device_type: str = "cisco_ios"


def parse_devices(path: pathlib.Path) -> list[DeviceRecord]:
    if not path.exists():
        raise FileNotFoundError(f"Device file not found: {path}")

    devices: list[DeviceRecord] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"ip", "username", "password"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(
                "Device file must include headers: ip,username,password (secret/device_type optional)"
            )

        for row in reader:
            devices.append(
                DeviceRecord(
                    ip=row["ip"].strip(),
                    username=row["username"].strip(),
                    password=row["password"].strip(),
                    secret=row.get("secret", "").strip() or None,
                    device_type=row.get("device_type", "cisco_ios").strip() or "cisco_ios",
                )
            )
    return devices


def ensure_directory(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def backup_config(conn: ConnectHandler, device: DeviceRecord, backup_dir: pathlib.Path) -> pathlib.Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{device.ip}_running_config_{timestamp}.cfg"
    backup_path = backup_dir / filename

    logging.info("Backing up running config for %s", device.ip)
    running_config = conn.send_command("show running-config")
    backup_path.write_text(running_config, encoding="utf-8")
    return backup_path


def upload_image(
    conn: ConnectHandler,
    device: DeviceRecord,
    image_path: pathlib.Path,
    remote_dir: str,
) -> str:
    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    remote_path = f"{remote_dir.rstrip('/')}/{image_path.name}"
    logging.info("Uploading image to %s:%s", device.ip, remote_path)

    transfer_result = file_transfer(
        conn,
        source_file=str(image_path),
        dest_file=image_path.name,
        file_system=remote_dir,
        direction="put",
        overwrite_file=False,
    )

    if not transfer_result.get("file_exists") and not transfer_result.get("file_transferred"):
        raise RuntimeError(f"SCP upload failed for {device.ip}")

    return remote_path


def confirm_image(conn: ConnectHandler, image_path: str) -> bool:
    logging.info("Confirming image presence: %s", image_path)
    output = conn.send_command(f"dir {image_path}")
    return "No such file" not in output


def set_boot_system(conn: ConnectHandler, image_path: str) -> None:
    logging.info("Setting boot system to %s", image_path)
    conn.send_config_set(["no boot system", f"boot system {image_path}"])
    conn.save_config()


def push_config(conn: ConnectHandler, config_path: pathlib.Path) -> None:
    logging.info("Pushing config from %s", config_path)
    config_lines = config_path.read_text(encoding="utf-8").splitlines()
    if not config_lines:
        raise ValueError(f"Backup config file is empty: {config_path}")
    conn.send_config_set(config_lines)
    conn.save_config()


def build_connection(device: DeviceRecord) -> ConnectHandler:
    logging.info("Connecting to %s", device.ip)
    conn = ConnectHandler(
        device_type=device.device_type,
        host=device.ip,
        username=device.username,
        password=device.password,
        secret=device.secret,
    )
    if device.secret:
        conn.enable()
    return conn


def process_device(
    device: DeviceRecord,
    image_path: pathlib.Path,
    remote_dir: str,
    backup_dir: pathlib.Path,
) -> None:
    conn = build_connection(device)
    try:
        backup_path = backup_config(conn, device, backup_dir)
        remote_image = upload_image(conn, device, image_path, remote_dir)
        if not confirm_image(conn, remote_image):
            raise RuntimeError(f"Image verification failed for {device.ip}")
        set_boot_system(conn, remote_image)
        push_config(conn, backup_path)
        logging.info("Completed workflow for %s", device.ip)
    finally:
        conn.disconnect()


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage Cisco Catalyst device workflows.")
    parser.add_argument("--devices", required=True, type=pathlib.Path, help="CSV file of devices")
    parser.add_argument("--image", required=True, type=pathlib.Path, help="IOS image path")
    parser.add_argument(
        "--remote-dir",
        default="flash:",
        help="Remote file system path (default: flash:)",
    )
    parser.add_argument(
        "--backup-dir",
        default=pathlib.Path("backups"),
        type=pathlib.Path,
        help="Local directory for config backups",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ensure_directory(args.backup_dir)

    devices = parse_devices(args.devices)
    if not devices:
        logging.error("No devices found in %s", args.devices)
        return 1

    for device in devices:
        try:
            process_device(device, args.image, args.remote_dir, args.backup_dir)
        except Exception as exc:  # noqa: BLE001 - surface workflow failures per device
            logging.exception("Failed for %s: %s", device.ip, exc)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
