#!/usr/bin/env python3
"""ROS 2 node: prints which way and how far to turn the pan motor so the camera centres the object.

Subscribes (from iris_detector_node):
    detected   std_msgs/Bool
    offset     geometry_msgs/PointStamped, x in -1..1 (+ = right of centre)

Prints one line per camera frame, e.g.
    RIGHT  3.10 deg
    LEFT   1.45 deg
    CENTER
    STOP   no detection for 0.50 s

Run with ROS sourced (system python, no venv needed):
    source /opt/ros/jazzy/setup.bash
    python3 iris_tracker_node.py --ros-args -r __ns:=/iris
"""
import math
import time

import rclpy
from geometry_msgs.msg import PointStamped
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool


class IrisTracker(Node):
    def __init__(self):
        super().__init__("tracker")
        self.declare_parameter("hfov_deg", 62.2)       # imx219 standard lens, horizontal
        self.declare_parameter("gain", 0.5)            # fraction of the error to turn per frame
        self.declare_parameter("max_step_deg", 5.0)    # largest single motor step
        self.declare_parameter("tolerance_deg", 2.0)   # below this the object counts as centred
        self.declare_parameter("lost_timeout", 0.5)    # s without detection before STOP

        p = lambda name: self.get_parameter(name).value
        self.tan_half_fov = math.tan(math.radians(p("hfov_deg")) / 2)
        self.gain = p("gain")
        self.max_step = p("max_step_deg")
        self.tolerance = p("tolerance_deg")
        self.lost_timeout = p("lost_timeout")

        self.last_seen = time.monotonic()
        self.stopped = True

        self.create_subscription(Bool, "detected", self.on_detected, 10)
        self.create_subscription(PointStamped, "offset", self.on_offset, 10)
        self.create_timer(0.05, self.check_lost)
        print("tracker ready, waiting for detections", flush=True)

    def on_detected(self, msg: Bool):
        if msg.data:
            self.last_seen = time.monotonic()

    def on_offset(self, msg: PointStamped):
        self.last_seen = time.monotonic()
        self.stopped = False
        # Normalised image offset -> horizontal angle (pinhole camera).
        error = math.degrees(math.atan(msg.point.x * self.tan_half_fov))
        if abs(error) <= self.tolerance:
            print("CENTER", flush=True)
            return
        step = min(self.max_step, self.gain * abs(error))
        direction = "RIGHT" if error > 0 else "LEFT "
        print(f"{direction}  {step:.2f} deg", flush=True)

    def check_lost(self):
        if not self.stopped and time.monotonic() - self.last_seen > self.lost_timeout:
            self.stopped = True
            print(f"STOP   no detection for {self.lost_timeout:.2f} s", flush=True)


def main():
    rclpy.init()
    node = IrisTracker()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
