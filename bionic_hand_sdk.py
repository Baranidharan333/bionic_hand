# # import can
# # import time


# # class BionicHandSDK:
# #     """
# #     Intelligent Bionic Robotic Hand SDK (CAN Protocol)
# #     Baudrate: 1 Mbps
# #     Standard Frame
# #     """

# #     def __init__(self, channel=0, bitrate=1000000):
# #         self.bus = can.Bus(
# #             interface='canalystii',
# #             channel=channel,
# #             bitrate=bitrate
# #         )

# #     # ------------------------------
# #     # Utility
# #     # ------------------------------

# #     @staticmethod
# #     def angle_to_step(angle_deg):
# #         """
# #         Convert 0–90 degree to 0–4095 step
# #         """
# #         angle_deg = max(0, min(90, angle_deg))
# #         return int((angle_deg / 90.0) * 4095)

# #     @staticmethod
# #     def step_to_angle(step):
# #         return (step / 4095.0) * 90.0

# #     def send(self, arbitration_id, data):
# #         msg = can.Message(
# #             arbitration_id=arbitration_id,
# #             data=data,
# #             is_extended_id=False
# #         )
# #         self.bus.send(msg)
# #         time.sleep(0.01)

# #     # ------------------------------
# #     # Power Control
# #     # ------------------------------

# #     def power_on(self, can_id=0x01):
# #         self.send(can_id, [0x03, 0x11])
# #         print("Power ON ✅")

# #     def power_off(self, can_id=0x01):
# #         self.send(can_id, [0x03, 0x00])
# #         print("Power OFF ❌")

# #     # ------------------------------
# #     # Torque Control
# #     # ------------------------------

# #     def enable_torque(self, can_id=0x01):
# #         # Byte0 Byte1 Byte2 Byte3
# #         # 10 ID TorqueValue 00
# #         self.send(can_id, [0x10, 0x00, 0x01, 0x00])
# #         print("Torque Enabled ✅")

# #     def disable_torque(self, can_id=0x01):
# #         self.send(can_id, [0x10, 0x00, 0x00, 0x00])
# #         print("Torque Disabled ❌")

# #     # ------------------------------
# #     # Single Finger Control
# #     # ------------------------------

# #     def set_single_finger_position(self, can_id, finger_id, angle_deg):
# #         step = self.angle_to_step(angle_deg)

# #         self.send(can_id, [0x04, finger_id, step & 0xFF, 0x00])
# #         print(f"Finger {finger_id} → {angle_deg}°")

# #     # ------------------------------
# #     # All Finger Position Mode
# #     # ------------------------------

# #     def set_all_positions(self, can_id, angle_list):
# #         """
# #         angle_list = [a1, a2, a3, a4, a5, a6]
# #         """

# #         steps = [self.angle_to_step(a) for a in angle_list]

# #         data = [
# #             0xA3,
# #             steps[0] & 0xFF,
# #             steps[1] & 0xFF,
# #             steps[2] & 0xFF,
# #             steps[3] & 0xFF,
# #             steps[4] & 0xFF,
# #             steps[5] & 0xFF,
# #             0x00
# #         ]

# #         self.send(can_id, data)
# #         print("All Fingers Updated ✅")

# #     # ------------------------------
# #     # Query Angles
# #     # ------------------------------

# #     def query_angles(self, can_id=0x01):
# #         self.send(can_id, [0xA1, 0x01])

# #         msg = self.bus.recv(timeout=1)

# #         if msg:
# #             angles = [
# #                 self.step_to_angle(v) for v in msg.data[2:8]
# #             ]
# #             print("Current Angles:", angles)
# #             return angles
# #         else:
# #             print("No response ❌")
# #             return None

# #     # ------------------------------
# #     # Status Read
# #     # ------------------------------

# #     def read_status(self, can_id=0x01):
# #         self.send(can_id, [0xD3, 0x01, 0, 0, 0, 0, 0, 0])

# #         msg = self.bus.recv(timeout=1)

# #         if msg:
# #             voltage = msg.data[2] * 0.1
# #             temp = msg.data[3]
# #             current = msg.data[4] * 6.5
# #             print(f"Voltage: {voltage}V | Temp: {temp}°C | Current: {current}mA")
# #         else:
# #             print("No status response")

# #     # ------------------------------
# #     # Shutdown
# #     # ------------------------------

# #     def close(self):
# #         self.bus.shutdown()
# #         print("CAN Closed Cleanly ✅")


# import can
# import time
# import threading


# class BionicHandSDK:

#     MAX_STEP = 4095
#     MAX_DEGREE = 90.0

#     # Gesture mapping (Manual Action Modes)
#     GESTURES = {
#         "open": 0x01,
#         "fist": 0x02,
#         "index": 0x03,
#         "middle": 0x04,
#         "ring": 0x05,
#         "little": 0x06,
#         "ok": 0x07
#     }

#     def __init__(self,
#                  interface="socketcan",
#                  channel="can0",
#                  bitrate=1000000,
#                  device_id=0x01):

#         self.device_id = device_id

#         self.bus = can.Bus(
#             interface=interface,
#             channel=channel,
#             bitrate=bitrate
#         )

#         self._running = False
#         self._feedback_thread = None
#         self.latest_angles = [0]*6

#     # --------------------------------------------------
#     # Utility
#     # --------------------------------------------------

#     @staticmethod
#     def angle_to_step(angle):
#         angle = max(0, min(90, angle))
#         return int((angle / 90.0) * 4095)

#     @staticmethod
#     def step_to_angle(step):
#         return (step / 4095.0) * 90.0

#     def send(self, data):
#         msg = can.Message(
#             arbitration_id=self.device_id,
#             data=data,
#             is_extended_id=False
#         )
#         self.bus.send(msg)
#         time.sleep(0.005)

#     # --------------------------------------------------
#     # POWER
#     # --------------------------------------------------

#     def power_on(self):
#         self.send([0x03, 0x11])
#         print("Power ON ✅")

#     def power_off(self):
#         self.send([0x03, 0x00])
#         print("Power OFF ❌")

#     # --------------------------------------------------
#     # TORQUE SWITCH
#     # --------------------------------------------------

#     def enable_torque(self):
#         self.send([0x10, 0x00, 0x01, 0x00])
#         print("Torque Enabled ✅")

#     def disable_torque(self):
#         self.send([0x10, 0x00, 0x00, 0x00])
#         print("Torque Disabled ❌")

#     # --------------------------------------------------
#     # GESTURES
#     # --------------------------------------------------

#     def gesture(self, name):
#         if name not in self.GESTURES:
#             raise ValueError("Invalid gesture")

#         self.send([0x03, self.GESTURES[name]])
#         print(f"Gesture → {name}")

#     # --------------------------------------------------
#     # SINGLE FINGER CONTROL
#     # --------------------------------------------------

#     def set_single_position(self, finger_id, angle):
#         step = self.angle_to_step(angle)
#         self.send([0x04, finger_id, step & 0xFF, 0x00])
#         print(f"Finger {finger_id} → {angle}°")

#     def set_single_speed(self, finger_id, speed):
#         self.send([0x09, finger_id, speed, 0x00])

#     def set_single_acceleration(self, finger_id, accel):
#         self.send([0x08, finger_id, accel, 0x00])

#     def set_single_torque_limit(self, finger_id, torque):
#         self.send([0x10, finger_id, torque, 0x00])

#     # --------------------------------------------------
#     # ALL FINGER POSITION MODE
#     # --------------------------------------------------

#     def set_all_positions(self, angles):
#         steps = [self.angle_to_step(a) for a in angles]

#         data = [
#             0xA3,
#             steps[0] & 0xFF,
#             steps[1] & 0xFF,
#             steps[2] & 0xFF,
#             steps[3] & 0xFF,
#             steps[4] & 0xFF,
#             steps[5] & 0xFF,
#             0x00
#         ]

#         self.send(data)

#     # --------------------------------------------------
#     # QUERY ANGLES
#     # --------------------------------------------------

#     def query_angles(self):
#         self.send([0xA1, 0x01])

#         msg = self.bus.recv(timeout=1)

#         if msg:
#             steps = msg.data[2:8]
#             self.latest_angles = [
#                 self.step_to_angle(s) for s in steps
#             ]
#             return self.latest_angles
#         return None

#     # --------------------------------------------------
#     # STATUS
#     # --------------------------------------------------

#     def read_status(self):
#         self.send([0xD3, 0x01, 0, 0, 0, 0, 0, 0])
#         msg = self.bus.recv(timeout=1)

#         if msg:
#             voltage = msg.data[2] * 0.1
#             temp = msg.data[3]
#             current = msg.data[4] * 6.5

#             return {
#                 "voltage": voltage,
#                 "temperature": temp,
#                 "current_mA": current
#             }

#         return None

#     # --------------------------------------------------
#     # DEBUG READ / WRITE
#     # --------------------------------------------------

#     def read_servo_limits(self, finger_id):
#         self.send([0xD1, finger_id, 0, 0, 0, 0, 0, 0])
#         return self.bus.recv(timeout=1)

#     def write_servo_limits(self, finger_id, min_val, max_val, correction):
#         self.send([0xD2, finger_id, min_val, max_val, correction, 0, 0, 0])

#     # --------------------------------------------------
#     # CHANGE DEVICE ID
#     # --------------------------------------------------

#     def change_device_id(self, new_id):
#         self.send([0x2E, new_id])
#         print("Device ID changed")

#     # --------------------------------------------------
#     # FEEDBACK THREAD
#     # --------------------------------------------------

#     def start_feedback(self, interval=0.1):

#         def loop():
#             while self._running:
#                 angles = self.query_angles()
#                 if angles:
#                     print("Angles:", angles)
#                 time.sleep(interval)

#         self._running = True
#         self._feedback_thread = threading.Thread(target=loop)
#         self._feedback_thread.start()

#     def stop_feedback(self):
#         self._running = False
#         if self._feedback_thread:
#             self._feedback_thread.join()

#     # --------------------------------------------------
#     # SAFE SHUTDOWN
#     # --------------------------------------------------

#     def shutdown(self):
#         self.stop_feedback()
#         self.bus.shutdown()
#         print("CAN Closed Cleanly ✅")



import can
import time
import threading

if not hasattr(can, "rc"):
    raise RuntimeError(
        "Detected incompatible 'can' package at "
        f"{getattr(can, '__file__', '<unknown>')}. "
        "Uninstall 'can' and install 'python-can' (pip uninstall can; pip install python-can)."
    )

try:
    CANBus = can.Bus
except AttributeError:
    from can.interface import Bus as CANBus  # type: ignore

try:
    CANMessage = can.Message
except AttributeError:
    from can.message import Message as CANMessage  # type: ignore


class BionicHandSDK:
    """
    Intelligent Bionic Robotic Hand SDK
    CAN Protocol – SocketCAN
    Default Baudrate: 1 Mbps
    """

    MAX_STEP = 4095
    MAX_DEGREE = 90.0

    FINGER_MAP = {
        "little": 1,
        "ring": 2,
        "middle": 3,
        "index": 4,
        "thumb": 5,
        "thumb_base": 6
    }

    GESTURES = {
        "open": 0x01,
        "fist": 0x02,
        "index": 0x03,
        "middle": 0x04,
        "ring": 0x05,
        "little": 0x06,
        "ok": 0x07
    }

    def __init__(self, channel="can0", bitrate=1000000, device_id=0x01):
        self.device_id = device_id

        self.bus = CANBus(
            interface="socketcan",
            channel=channel,
            bitrate=bitrate
        )

        self._running = False
        self._feedback_thread = None
        self.latest_angles = [0]*6

    # ==========================================================
    # Utility
    # ==========================================================

    @staticmethod
    def angle_to_step(angle):
        angle = max(0, min(90, angle))
        return int((angle / 90.0) * 4095)

    @staticmethod
    def step_to_angle(step):
        return (step / 4095.0) * 90.0

    def _send(self, data):
        msg = CANMessage(
            arbitration_id=self.device_id,
            data=data,
            is_extended_id=False
        )
        self.bus.send(msg)
        time.sleep(0.005)

    # ==========================================================
    # POWER
    # ==========================================================

    def power_on(self):
        self._send([0x03, 0x11])
        print("Power ON ✅")

    def power_off(self):
        self._send([0x03, 0x00])
        print("Power OFF ❌")

    # ==========================================================
    # TORQUE
    # ==========================================================

    def enable_torque(self):
        self._send([0x10, 0x00, 0x01, 0x00])
        print("Torque Enabled ✅")

    def disable_torque(self):
        self._send([0x10, 0x00, 0x00, 0x00])
        print("Torque Disabled ❌")

    # ==========================================================
    # GESTURE
    # ==========================================================

    def gesture(self, name):
        if name not in self.GESTURES:
            raise ValueError("Invalid gesture")

        self._send([0x03, self.GESTURES[name]])
        print(f"Gesture → {name}")

    # ==========================================================
    # SINGLE FINGER CONTROL
    # ==========================================================

    def set_single_position(self, finger_name, angle):
        finger_id = self.FINGER_MAP[finger_name]
        step = self.angle_to_step(angle)

        self._send([0x04, finger_id, step & 0xFF, 0x00])
        print(f"{finger_name} → {angle}°")

    def set_single_speed(self, finger_name, speed):
        finger_id = self.FINGER_MAP[finger_name]
        self._send([0x09, finger_id, speed, 0x00])

    def set_single_acceleration(self, finger_name, accel):
        finger_id = self.FINGER_MAP[finger_name]
        self._send([0x08, finger_id, accel, 0x00])

    def set_single_torque_limit(self, finger_name, torque):
        finger_id = self.FINGER_MAP[finger_name]
        self._send([0x10, finger_id, torque, 0x00])

    # ==========================================================
    # ALL FINGERS POSITION MODE
    # ==========================================================

    def set_all_positions(self, angles):
        steps = [self.angle_to_step(a) for a in angles]

        data = [
            0xA3,
            steps[0] & 0xFF,
            steps[1] & 0xFF,
            steps[2] & 0xFF,
            steps[3] & 0xFF,
            steps[4] & 0xFF,
            steps[5] & 0xFF,
            0x00
        ]

        self._send(data)

    # ==========================================================
    # QUERY ANGLES
    # ==========================================================

    def query_angles(self):
        self._send([0xA1, 0x01])
        msg = self.bus.recv(timeout=1)

        if msg:
            steps = msg.data[2:8]
            self.latest_angles = [
                self.step_to_angle(s) for s in steps
            ]
            return self.latest_angles
        return None

    # ==========================================================
    # STATUS
    # ==========================================================

    def read_status(self):
        self._send([0xD3, 0x01, 0, 0, 0, 0, 0, 0])
        msg = self.bus.recv(timeout=1)

        if msg:
            voltage = msg.data[2] * 0.1
            temp = msg.data[3]
            current = msg.data[4] * 6.5

            return {
                "voltage": voltage,
                "temperature": temp,
                "current_mA": current
            }
        return None

    # ==========================================================
    # FEEDBACK THREAD
    # ==========================================================

    def start_feedback(self, interval=0.2):

        def loop():
            while self._running:
                angles = self.query_angles()
                if angles:
                    print("Angles:", angles)
                time.sleep(interval)

        self._running = True
        self._feedback_thread = threading.Thread(target=loop)
        self._feedback_thread.start()

    def stop_feedback(self):
        self._running = False
        if self._feedback_thread:
            self._feedback_thread.join()

    # ==========================================================
    # CHANGE DEVICE ID
    # ==========================================================

    def change_device_id(self, new_id):
        self._send([0x2E, new_id])
        self.device_id = new_id
        print(f"Device ID changed to {hex(new_id)}")

    # ==========================================================
    # SHUTDOWN
    # ==========================================================

    def shutdown(self):
        self.stop_feedback()
        self.bus.shutdown()
        print("CAN Closed Cleanly ✅")
