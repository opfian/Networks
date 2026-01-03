# Networks Repository

## Catalyst Maintenance Script

`catalyst_maintenance.py` uses Netmiko to log in to Cisco Catalyst devices, back up the
running configuration, upload a new IOS image via SCP, confirm the image is present,
set the boot system, and push the backed-up configuration back onto the device.

### Device Inventory File

Provide a CSV file with the following headers:

```csv
ip,username,password,secret,device_type
192.0.2.10,admin,pa55w0rd,enablepw,cisco_ios
192.0.2.11,admin,pa55w0rd,,cisco_ios
```

A sample file is included as `devices.csv`.

### Usage

```bash
python3 catalyst_maintenance.py \
  --devices devices.csv \
  --image /path/to/cat9k_iosxe.bin \
  --remote-dir flash: \
  --backup-dir backups
```

### Notes

- Ensure SSH and SCP are enabled on the devices.
- The script writes configuration backups locally under the chosen backup directory.
- The workflow sets the boot system to the newly uploaded image and saves the config.
