"""Tests against a simulated hand on a python-can virtual bus (no hardware needed).

Run:  cd hand_sdk && python3 -m unittest discover -s tests -v
"""
import os
import sys
import threading
import unittest

import can

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bionic_hand import BionicHand, HandNotResponding  # noqa: E402
from bionic_hand import protocol as p  # noqa: E402


class FakeHand(threading.Thread):
    """Answers A1 01 / A1 02 / D1 / D3 like the manual describes."""

    def __init__(self, channel, device_id=0x01, reply_id=0x01):
        super().__init__(daemon=True)
        self.bus = can.Bus(interface="virtual", channel=channel)
        self.device_id = device_id
        self.reply_id = reply_id
        self.stop = threading.Event()
        self.angles = [10, 20, 30, 40, 50, 90]

    def run(self):
        while not self.stop.is_set():
            m = self.bus.recv(0.05)
            if m is None or m.arbitration_id != self.device_id:
                continue
            d = bytes(m.data)
            out = None
            if d[:2] == b"\xA1\x01":
                out = bytes([0xA1, 0x01] + self.angles)
            elif d[:2] == b"\xA1\x02":
                out = bytes([0xA1, 0x02, 0x01, 0x00, 0x03])
            elif d[0] == 0xD1:
                # min=100, max=3995, correction=-5 (bit11 sign) little-endian
                out = bytes([0xD1, d[1]]) + (100).to_bytes(2, "little") + (3995).to_bytes(2, "little") \
                    + (0x800 | 5).to_bytes(2, "little")
            elif d[0] == 0xD3:
                out = bytes([0xD3, d[1], 120, 30 + d[1]]) + (40).to_bytes(2, "little") + b"\x00\x00"
            if out:
                self.bus.send(can.Message(arbitration_id=self.reply_id, data=out, is_extended_id=False))

    def close(self):
        self.stop.set()
        self.join(1)
        self.bus.shutdown()


class SDKTest(unittest.TestCase):
    def setUp(self):
        self.ch = f"t{id(self)}"
        self.fake = FakeHand(self.ch)
        self.fake.start()
        self.hand = BionicHand(bus=can.Bus(interface="virtual", channel=self.ch), timeout=0.5)

    def tearDown(self):
        self.hand.close()
        self.hand.bus.shutdown()
        self.fake.close()

    def test_angles(self):
        a = self.hand.query_angles()
        self.assertEqual(a.as_list(), [10, 20, 30, 40, 50, 90])
        self.assertEqual(a.by_name()["index"], 40)
        self.assertEqual(a.percent[6], 100.0)

    def test_status(self):
        s = self.hand.read_status("index")
        self.assertEqual((s.finger, s.voltage_v, s.temperature_c, s.position_steps), (4, 12.0, 34, 40))
        self.assertEqual(len(self.hand.read_all_status()), 6)

    def test_limits(self):
        lim = self.hand.read_limits(2)
        self.assertEqual((lim.servo_min, lim.servo_max, lim.correction), (100, 3995, -5))

    def test_version(self):
        self.assertEqual(self.hand.query_version(), "01 00 03")

    def test_snapshot_and_stream(self):
        snap = self.hand.snapshot()
        self.assertFalse(snap.errors)
        self.assertEqual(len(snap.status), 6)
        got = [s for _, s in zip(range(3), self.hand.stream(rate_hz=50))]
        self.assertTrue(all(s.angles for s in got))

    def test_ignores_unrelated_frames(self):
        other = can.Bus(interface="virtual", channel=self.ch)
        other.send(can.Message(arbitration_id=0x55, data=[0xD3, 0x09, 0, 0, 0, 0, 0, 0], is_extended_id=False))
        self.assertEqual(self.hand.read_status(1).finger, 1)
        other.shutdown()

    def test_wrong_id_times_out(self):
        self.hand.device_id = 0x05
        self.hand.timeout = 0.15
        with self.assertRaises(HandNotResponding):
            self.hand.query_angles()


class TwoHandScanTest(unittest.TestCase):
    def test_scan_finds_left_and_right(self):
        from bionic_hand.sim import SimulatedHands
        sim = SimulatedHands("two-hands", ids=(0x01, 0x02))
        sim.start()
        bus = can.Bus(interface="virtual", channel="two-hands")
        hand = BionicHand(bus=bus)
        try:
            found = hand.scan(1, 8, timeout=0.05)
            self.assertEqual(sorted(found), [1, 2])
            self.assertEqual(hand.read_status(4, device_id=2).finger, 4)
            self.assertEqual(hand.query_version(device_id=2), "01 00 02")
        finally:
            hand.close()
            bus.shutdown()
            sim.close()


class ControlTest(unittest.TestCase):
    def setUp(self):
        from bionic_hand.sim import SimulatedHands
        self.sim = SimulatedHands("ctl", ids=(0x01, 0x02), reply_offset=0x100)
        self.sim.start()
        self.bus = can.Bus(interface="virtual", channel="ctl")
        self.hand = BionicHand(bus=self.bus)

    def tearDown(self):
        self.hand.close()
        self.bus.shutdown()
        self.sim.close()

    def wait_for(self, cid, expected, timeout=2.0):
        import time
        end = time.time() + timeout
        while time.time() < end:
            got = self.hand.query_angles(cid).as_list()
            if got == expected:
                return got
            time.sleep(0.05)
        self.fail(f"hand 0x{cid:02X} angles {got} never reached {expected}")

    def test_open_close_finger_pose(self):
        self.hand.close_hand(device_id=2)
        self.wait_for(2, [90] * 6)
        self.hand.open_hand(device_id=2)
        self.wait_for(2, [0] * 6)
        self.hand.set_finger("index", 60, device_id=2)
        self.wait_for(2, [0, 0, 0, 60, 0, 0])
        self.hand.set_pose([1, 2, 3, 4, 5, 6], device_id=2)
        self.wait_for(2, [1, 2, 3, 4, 5, 6])
        self.assertEqual(self.hand.query_angles(1).as_list(), [10, 20, 30, 40, 50, 90])  # other hand untouched

    def test_feedback_id_is_recorded(self):
        self.hand.query_angles(2)
        self.assertEqual(self.hand.reply_ids[2], 0x102)


class ProtocolTest(unittest.TestCase):
    def test_control_encoders(self):
        self.assertEqual(p.gesture_request("fist"), b"\x03\x02")
        self.assertEqual(p.finger_position_request("thumb", 45), bytes([0x04, 5, 45, 0]))
        self.assertEqual(p.pose_request([0, 1, 2, 3, 4, 5]), bytes([0xA3, 0, 1, 2, 3, 4, 5, 0]))
        self.assertEqual(p.setting_request("speed", 50), bytes([0x05, 50, 0, 0]))
        self.assertEqual(p.setting_request("torque", 70, finger=4), bytes([0x10, 4, 70, 0]))
        for bad in (lambda: p.gesture_request("wave"), lambda: p.finger_position_request(1, 256),
                    lambda: p.pose_request([0] * 5), lambda: p.setting_request("jerk", 1)):
            with self.assertRaises(ValueError):
                bad()

    def test_finger_names(self):
        self.assertEqual(p.finger_id("thumb_base"), 6)
        self.assertEqual(p.finger_id("3"), 3)
        with self.assertRaises(ValueError):
            p.finger_id(7)

    def test_big_endian_option(self):
        data = bytes([0xD3, 1, 120, 30, 0x00, 0x28, 0, 0])
        self.assertEqual(p.decode_status(data, "big").position_steps, 40)

    def test_real_hand_replies(self):
        """Frames captured from the real right hand (2026-11-06)."""
        lim = p.decode_limits(bytes.fromhex("d1 01 d0 02 f3 08 e8 03"))
        self.assertEqual((lim.servo_min, lim.servo_max), (720, 2291))
        st = p.decode_status(bytes.fromhex("d3 01 40 2a ce 08 d0 07"))
        self.assertEqual((st.voltage_v, st.temperature_c, st.position_steps, st.extra), (6.4, 42, 2254, 2000))
        self.assertTrue(lim.servo_min <= st.position_steps <= lim.servo_max)
        # manual: angle = (max - steps) * 90 / (max - min); the hand reported 2 for this finger
        self.assertEqual(int((lim.servo_max - st.position_steps) * 90 / (lim.servo_max - lim.servo_min)), 2)
        with self.assertRaises(ValueError):
            p.finger_position_request(1, 91)

    def test_error_frame_text(self):
        txt = p.describe_error_frame(0x024, bytes([0, 0x30, 0, 0, 0, 0, 0x90, 0]))
        self.assertIn("no ACK", txt)
        self.assertIn("tx_err=144", txt)

    def test_bad_reply(self):
        with self.assertRaises(p.ProtocolError):
            p.decode_angles(b"\xA1\x02\x00\x00\x00\x00\x00\x00")


if __name__ == "__main__":
    unittest.main()
