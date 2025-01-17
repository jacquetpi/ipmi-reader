# Simple IPMI reader 

Easily measure IPMI values related to GPUs

## Features

Dump in a CSV file IPMI values related to GPUs along indicators from ```
nvidia-smi``` (that must be preinstalled)

## Requirements

Curl and ipmitool

## Installation

```bash
git clone https://github.com/jacquetpi/ipmi-reader
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Usage

```bash
source venv/bin/activate
python3 ipmi-reader.py --help
```

To dump on default ```measures.csv``` while also displaying measures to the console
```bash
source venv/bin/activate
python3 ipmi-reader.py --live
```

To change default values:
```bash
source venv/bin/activate
python3 ipmi-reader.py --delay=(sec) --precision=(number of digits) --output=measures.csv
```