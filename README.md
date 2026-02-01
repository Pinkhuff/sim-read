# SIM Card Reader

Read data from SIM/USIM cards using a PC/SC compatible smart card reader.

## Quick Start

```bash
# Install dependencies
sudo apt install pcscd pcsc-tools libpcsclite-dev
pip install pyscard

# Run
python main.py
```

## Requirements

### System Packages

```bash
sudo apt update
sudo apt install pcscd pcsc-tools libpcsclite-dev
```

### Python Packages

```bash
pip install pyscard
```

Or using a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
pip install pyscard
```

## Hardware

- USB Smart Card Reader (PC/SC compatible)
- SIM card adapter (if using nano/micro SIM)

## Usage

```
python main.py [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `-s`, `--save` | Save output to file (uses ICCID as filename) |
| `-o FILE`, `--output FILE` | Save output to custom filename |
| `-r NUM`, `--reader NUM` | Select reader by index (default: 0) |
| `-l`, `--list` | List available readers and exit |
| `-h`, `--help` | Show help message |

### Examples

```bash
# Read SIM and display output
python main.py

# Save output using ICCID as filename
python main.py --save
# Creates: xxxxxxxxxxxxxxxxxxx_yyyymmdd_hhmmss.txt

# Save to custom filename
python main.py --output my_sim_dump.txt

# List available readers
python main.py --list

# Use a specific reader (e.g., second reader)
python main.py --reader 1

# Combine options
python main.py --reader 1 --save
```

## Data Retrieved

| Field | Description |
|-------|-------------|
| ICCID | SIM card serial number (19-20 digits) |
| IMSI | International Mobile Subscriber Identity |
| MCC | Mobile Country Code |
| MNC | Mobile Network Code |
| MSIN | Mobile Subscriber Identification Number |
| SPN | Service Provider Name |
| MSISDN | Phone number (if stored on SIM) |
| SMSC | SMS Service Center number |
| LOCI | Location info (TMSI, LAC, last network) |
| PLMNs | Preferred/Forbidden network list |
| ADN | Contacts stored on SIM |
| SMS | Text messages stored on SIM |
| FDN | Fixed Dialing Numbers |
| SDN | Service Dialing Numbers |
| LND | Last Numbers Dialed |

## Troubleshooting

### No readers found

```bash
# Check reader is connected
lsusb | grep -i smart

# Start PC/SC daemon
sudo systemctl start pcscd
sudo systemctl enable pcscd

# Verify reader is detected
python main.py --list
```

### Card absent or mute

- Remove and reinsert the SIM card
- Ensure the SIM is properly seated in the adapter
- Clean the SIM contacts
- Restart pcscd:
  ```bash
  sudo systemctl restart pcscd
  ```

### Failed to connect to card

- Wait a moment after inserting the card:
  ```bash
  sleep 2 && python main.py
  ```
- Check if another application is using the reader
- Try unplugging and replugging the reader

### pyscard install fails

Install development libraries first:

```bash
sudo apt install libpcsclite-dev swig
pip install pyscard
```

### Not available for most fields

1. **PIN locked**: Some files require PIN verification
2. **USIM card**: The script automatically tries USIM mode
3. **Empty files**: Modern phones store data in phone memory, not SIM

### Permission denied

```bash
# Add user to pcscd group
sudo usermod -aG pcscd $USER

# Log out and back in, or run:
newgrp pcscd
```

### Check card communication

```bash
# List readers
opensc-tool --list-readers

# Get ATR (Answer To Reset)
opensc-tool -a

# Scan for cards
pcsc_scan
```

## Output File Format

When using `--save`, the output file contains:

```
============================================================
SIM CARD DATA DUMP
============================================================

--- ICCID (SIM Serial Number) ---
ICCID: xxxxxxxxxxxxxxxxxxx

--- IMSI ---
IMSI: xxxxxxxxxxxxxxx
  MCC: xxx
  MNC: xx
  MSIN: xxxxxxxxxx

[... more fields ...]

============================================================
DUMP COMPLETE
============================================================
```

## File Structure

```
sim-card/
├── main.py       # Full SIM data dump
├── requirements.txt  # Python dependencies
└── README.md         # This file
```

## Common ATR Values

| ATR Pattern | Card Type |
|-------------|-----------|
| 3B 9F 96... | USIM (3G/4G) |
| 3B 3F 94... | GSM SIM |
| 3B 9E 95... | USIM |

## Security Notes

- IMSI and ICCID are sensitive identifiers - do not share publicly
- Some files (FDN, Ki) are PIN2 protected
- The Ki (authentication key) cannot be read without special equipment
- Saved output files contain sensitive data - store securely

## License

MIT
