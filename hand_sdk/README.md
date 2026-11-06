# Bionic Hand CAN reader SDK

Read-only Python SDK for the Intelligent Bionic Robotic Hand (CAN protocol, manual v1.0.0 §3.3).
It never moves the hand: it only sends query/debug-read commands.

Requires `python-can` (`pip install python-can`) and a SocketCAN interface at 1 Mbps:

```bash
./can_up.sh            # can0 down -> 1 Mbps -> up, then prints status (asks for sudo)
./kill_port.sh [5000]  # free the web app's port (asks before killing)
./start_hand.sh        # both of the above, then starts the web app
```

The gs_usb adapter doesn't support `restart-ms`. If the bus goes BUS-OFF, run `./can_up.sh` again.

## Web app (Flask)

```bash
python3 webapp/app.py            # real hands on can0 -> http://127.0.0.1:5000
python3 webapp/app.py --sim      # two simulated hands (0x01, 0x02), no hardware needed
python3 webapp/app.py --channel can1 --host 0.0.0.0 --port 8000
```

- **Scan**: probes a CAN ID range and lists every hand that answers, with its command ID and its
  feedback ID (the CAN ID the replies actually arrive on; the manual doesn't document it).
- **Label**: mark each found hand as *Right* or *Left* (saved in `webapp/hands.json`).
- **Control**: Open / Close buttons, gestures (index, middle, ring, little, OK), power on/off, one slider
  per finger (moves while dragging, or set them all and press *Send pose*), and whole-hand speed / torque /
  acceleration settings.
- **Read**: each finger's actual position appears as a green bar beside its slider. Voltage, temperature,
  servo position (steps), servo limits and version are also available, refreshed 1 to 10 times per second.
- `--read-only` turns off every command that moves the hands.
- The header shows the can0 link state and warns when the interface is down or frames get no ACK.

Slider values are degrees 0–90, the same units the hand reports (verified on the real hand). The manual doesn't say whether 0° is open
or closed, so the Open and Close buttons use the hand's built-in gestures (`03 01` / `03 02`), which are unambiguous.

Both hands ship with ID 0x01. If they share an ID they can't be told apart, so connect one at a time to find each one's ID.

## Command line

Run from this folder:

```bash
python3 -m bionic_hand scan                      # find hands: listen, then probe IDs 0x01..0x7F
python3 -m bionic_hand diag                      # link state + does the hand answer?
python3 -m bionic_hand angles [--json]           # finger angles (degrees 0..90)
python3 -m bionic_hand status [--json]           # voltage / temperature / servo position (steps) per finger
python3 -m bionic_hand limits                    # servo min / max / correction per finger
python3 -m bionic_hand version
python3 -m bionic_hand monitor --rate 20 --status --csv log.csv
```

Global options: `--channel can0 --interface socketcan --id 0x01 --timeout 0.3 --byteorder little|big`.

## Python

```python
from bionic_hand import BionicHand

with BionicHand("can0") as hand:
    a = hand.query_angles()
    print(a.by_name())             # {'little': 10, 'ring': 20, ...}
    print(hand.read_status("index"))
    for snap in hand.stream(rate_hz=10, with_status=True):
        print(snap.angles.as_list(), snap.status[4].temperature_c)
        break
```

## Data read

| Command | Request | Reply decoded as |
|---|---|---|
| Query angles | `A1 01` | bytes 2..7 = finger 1..6 angle in degrees 0..90 |
| Query version | `A1 02` | bytes after `A1 02`, shown as hex (layout is undocumented) |
| Read limits | `D1 id 00..` | min, max, correction: 2 bytes each; correction uses BIT11 as the sign |
| Read status | `D3 id 00..` | voltage ×0.1 V, temperature °C, present servo position in steps (2 bytes; the manual's "Current Servo Value"), 2 undocumented bytes |

Finger IDs: 1 little, 2 ring, 3 middle, 4 index, 5 thumb, 6 thumb_base.

**Verified on the real hand:** 2-byte fields are little-endian. The angle byte follows the manual's formula
`angle = (max - steps) * 90 / (max - min)`, using the D1 limits and the D3 position.

## Tests

```bash
python3 -m unittest discover -s tests -v   # uses a simulated hand on a virtual bus
```
# bionic_hand
