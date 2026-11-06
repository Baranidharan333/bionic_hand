# bionic_hand

Python tools for the **Intelligent Bionic Robotic Hand** (6 DOF, CAN bus at 1 Mbps), used with the
OpenArm setup. The tools include an SDK, a command-line tool, a Flask web app for one or two hands,
and some older scripts.

Protocol reference: [`Robot Hand User Manual-En.pdf`](Robot%20Hand%20User%20Manual-En.pdf)
(v1.0.0, §3.3 CAN protocol). A text copy is in [`manual.txt`](manual.txt), and the CAN protocol
pages are saved as images in `can_page-11..13.png`.

## Repository layout

```
Bionic_hand/
├── hand_sdk/                  # Main package: use this
│   ├── bionic_hand/           # Python SDK + CLI (python3 -m bionic_hand)
│   ├── webapp/                # Flask web app (scan, label, control, live readback)
│   ├── tests/                 # Unit tests against a simulated hand
│   ├── can_up.sh              # Bring can0 up at 1 Mbps
│   ├── kill_port.sh           # Free the web app port
│   └── start_hand.sh          # can_up + kill_port + start web app
│
├── can_hand_control.py        # Legacy CLI: power, gestures, per-finger pos/speed/torque, CAN ID
├── can_hand_gui.py            # Legacy Tkinter GUI, one hand
├── dual_can_hand_gui_usb.py   # Legacy Tkinter GUI, left + right hand
├── connect_two_arms.py        # Connectivity check for two hands
├── torque_enable.py           # Power on the servos
├── torque_disable.py          # Power off the servos
├── bionic_hand_sdk.py         # Early SDK draft (mostly commented out)
└── Robot Hand User Manual-En.pdf, manual.txt, can_page-*.png
```

The legacy scripts default to a **CANalyst-II** adapter (`interface=canalystii`). `hand_sdk`
defaults to **SocketCAN** (`can0`, e.g. a gs_usb adapter).

## Requirements

- Linux with SocketCAN, plus a USB-to-CAN adapter
- Python 3.10+
- `pip install python-can flask`

> If you get an error about an incompatible `can` package, you have the wrong one installed:
> `pip uninstall can && pip install python-can`.

## Quick start

```bash
git clone git@github.com:Baranidharan333/bionic_hand.git
cd bionic_hand/hand_sdk

./can_up.sh                     # can0 -> 1 Mbps -> up (asks for sudo)
python3 -m bionic_hand diag     # is the link up, and does the hand answer?
python3 webapp/app.py           # open http://127.0.0.1:5000
```

No hardware? Run `python3 webapp/app.py --sim` to get two simulated hands.

`start_hand.sh` runs all three steps in one go. It uses a hard-coded path to `hand_sdk`, so
edit the `cd` line if your clone is in a different place.

### CAN adapter notes

- The bitrate must be **1 Mbps** (standard frames).
- The gs_usb adapter doesn't support `restart-ms`. If the bus goes **BUS-OFF**, run
  `./can_up.sh` again.
- Check the link with `ip -details link show can0` and watch the traffic with `candump can0`.

## Web app

```bash
python3 webapp/app.py                                  # real hands on can0
python3 webapp/app.py --sim                            # simulated hands
python3 webapp/app.py --read-only                      # monitoring only, never moves the hands
python3 webapp/app.py --channel can1 --host 0.0.0.0 --port 8000
```

- **Scan** finds every hand that answers in an ID range and shows each one's command and feedback CAN IDs.
- **Label** marks each hand as Left or Right. Labels are saved in `webapp/hands.json`.
- **Control** has Open/Close, the gestures (index, middle, ring, little, OK), power on/off,
  a 0–90° slider for each finger, and speed, torque and acceleration settings.
- **Read** shows live finger angles, voltage, temperature, servo position, limits and version.

## Command line

Run these from `hand_sdk/`:

```bash
python3 -m bionic_hand scan                 # find hands (probes IDs 0x01..0x7F)
python3 -m bionic_hand angles [--json]      # finger angles, 0..90°
python3 -m bionic_hand status [--json]      # voltage / temperature / servo position per finger
python3 -m bionic_hand limits               # servo min / max / correction
python3 -m bionic_hand version
python3 -m bionic_hand monitor --rate 20 --status --csv log.csv
```

Global options: `--channel can0 --interface socketcan --id 0x01 --timeout 0.3`.

## Python API

```python
from bionic_hand import BionicHand   # run from hand_sdk/, or add it to PYTHONPATH

with BionicHand("can0") as hand:
    print(hand.query_angles().by_name())   # {'little': 10, 'ring': 20, ...}
    print(hand.read_status("index"))
```

You can find the full SDK reference in [`hand_sdk/README.md`](hand_sdk/README.md).

## Protocol facts (verified on hardware)

| Item | Value |
|---|---|
| Finger IDs | 1 little, 2 ring, 3 middle, 4 index, 5 thumb, 6 thumb base |
| Query angles | `A1 01`. The reply bytes 2..7 are the angles of fingers 1..6, in degrees 0..90 |
| Gestures | `03 01` open, `03 02` close (fist) |
| Read limits | `D1 <finger>`: min, max and correction (2 bytes each, little-endian) |
| Read status | `D3 <finger>`: voltage ×0.1 V, temperature in °C, servo position in steps |
| Angle formula | `angle = (max - steps) * 90 / (max - min)` |

**Both hands ship with CAN ID `0x01`.** If they share an ID they can't be told apart, so
connect one hand at a time, scan it, and give it a new ID (e.g. with
`python3 can_hand_control.py set-can-id 0x02`, then `save-flash`).

## Tests

```bash
cd hand_sdk
python3 -m unittest discover -s tests -v
```

## Safety

- Keep fingers and objects out of the hand's path when you send motion commands.
- Use `--read-only` or the `diag`, `angles` and `status` CLI commands when you only need to monitor.
- If the hand behaves unexpectedly, run `torque_disable.py` or send power off.
