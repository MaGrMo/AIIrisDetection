#!/usr/bin/env python3
"""ROS 2 node: camera (libcamera) -> YOLO (NCNN) -> topics.

Publishes:
    image_annotated               sensor_msgs/Image (bgr8), frame with boxes drawn
    image_annotated/compressed    sensor_msgs/CompressedImage (jpeg), same frame
    detected                      std_msgs/Bool, True if an object is in the frame
    offset                        geometry_msgs/PointStamped, only when detected:
                                    x = horizontal offset from centre, -1 (left) .. 1 (right)
                                    y = vertical offset from centre, -1 (bottom) .. 1 (top)
                                    z = confidence of the detection

Run from the venv with ROS sourced:
    source /opt/ros/jazzy/setup.bash
    .venv/bin/python iris_detector_node.py --ros-args -r __ns:=/iris
"""
import os
import signal
import sys
import threading
import time

# Hide libcamera's INFO lines, keep warnings and errors.
os.environ.setdefault("LIBCAMERA_LOG_LEVELS", "*:WARN")

# rclpy, ROS messages and PyGObject come from the system; append so the venv's numpy/cv2 still win.
sys.path.append("/usr/lib/python3.12/site-packages")

import cv2
import gi
import numpy as np
import rclpy
from geometry_msgs.msg import PointStamped
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from rclpy.signals import SignalHandlerOptions
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import Bool

gi.require_version("Gst", "1.0")
from gi.repository import Gst
from ultralytics import YOLO


class IrisDetector(Node):
    def __init__(self):
        super().__init__("detector")
        self.declare_parameter("model", "best320_ncnn_model")
        self.declare_parameter("width", 800)
        self.declare_parameter("height", 600)
        self.declare_parameter("fps", 30)
        self.declare_parameter("imgsz", [320])
        self.declare_parameter("conf", 0.5)
        self.declare_parameter("frame_id", "camera")
        self.declare_parameter("publish_raw", True)
        self.declare_parameter("publish_compressed", True)
        self.declare_parameter("jpeg_quality", 70)
        self.declare_parameter("hdmi", False)
        self.declare_parameter("connector", 32)

        p = lambda name: self.get_parameter(name).value
        self.width, self.height = p("width"), p("height")
        imgsz = list(p("imgsz"))
        self.imgsz = imgsz[0] if len(imgsz) == 1 else tuple(imgsz)
        self.conf = p("conf")
        self.frame_id = p("frame_id")
        self.publish_raw = p("publish_raw")
        self.publish_compressed = p("publish_compressed")
        self.jpeg_quality = p("jpeg_quality")

        # Sensor-style QoS for video: drop old frames instead of queueing them.
        video_qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                               history=HistoryPolicy.KEEP_LAST, depth=1)
        self.pub_image = self.create_publisher(Image, "image_annotated", video_qos)
        self.pub_jpeg = self.create_publisher(CompressedImage, "image_annotated/compressed", video_qos)
        self.pub_detected = self.create_publisher(Bool, "detected", 10)
        self.pub_offset = self.create_publisher(PointStamped, "offset", 10)

        self.get_logger().info(f"loading model {p('model')}")
        self.model = YOLO(p("model"), task="detect")

        Gst.init(None)
        caps = f"video/x-raw,format=BGR,width={self.width},height={self.height},framerate={p('fps')}/1"
        self.cap_pipe = Gst.parse_launch(
            # Without an explicit role and format, libcamerasrc only offers the raw Bayer stream.
            f"libcamerasrc src::stream-role=video-recording "
            f"! video/x-raw,format=NV12,width={self.width},height={self.height},framerate={p('fps')}/1 "
            f"! videoconvert ! {caps} ! appsink name=sink max-buffers=1 drop=true sync=false"
        )
        self.sink = self.cap_pipe.get_by_name("sink")
        self.out_pipe = None
        if p("hdmi"):
            self.out_pipe = Gst.parse_launch(
                f"appsrc name=src is-live=true do-timestamp=true format=time caps={caps} "
                f"! videoconvert ! kmssink connector-id={p('connector')} sync=false"
            )
            self.src = self.out_pipe.get_by_name("src")
            self.out_pipe.set_state(Gst.State.PLAYING)
        self.cap_pipe.set_state(Gst.State.PLAYING)

        self.running = True
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        self.get_logger().info(f"running: camera {self.width}x{self.height}, model input {self.imgsz}")

    def grab(self):
        sample = self.sink.emit("try-pull-sample", Gst.SECOND)
        if sample is None:
            return None
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return None
        frame = np.frombuffer(info.data, np.uint8).reshape(self.height, self.width, 3).copy()
        buf.unmap(info)
        return frame

    def loop(self):
        frames, fps, last = 0, 0.0, time.time()
        while self.running and rclpy.ok():
            frame = self.grab()
            if frame is None:
                self.get_logger().warn("no frame from camera", throttle_duration_sec=5.0)
                continue
            stamp = self.get_clock().now().to_msg()

            result = self.model(frame, imgsz=self.imgsz, conf=self.conf, verbose=False)[0]
            boxes = result.boxes
            detected = len(boxes) > 0

            self.pub_detected.publish(Bool(data=detected))

            annotated = result.plot()
            cx, cy = self.width / 2, self.height / 2
            cv2.drawMarker(annotated, (int(cx), int(cy)), (255, 255, 255), cv2.MARKER_CROSS, 20, 1)

            if detected:
                best = int(boxes.conf.argmax())
                x1, y1, x2, y2 = boxes.xyxy[best].tolist()
                bx, by = (x1 + x2) / 2, (y1 + y2) / 2
                msg = PointStamped()
                msg.header.stamp = stamp
                msg.header.frame_id = self.frame_id
                msg.point.x = (bx - cx) / cx
                msg.point.y = (cy - by) / cy
                msg.point.z = float(boxes.conf[best])
                self.pub_offset.publish(msg)
                cv2.line(annotated, (int(cx), int(cy)), (int(bx), int(by)), (0, 255, 255), 2)
                cv2.putText(annotated, f"dx={msg.point.x:+.2f} dy={msg.point.y:+.2f}", (20, 75),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - last, 1e-6)) if frames else 0.0
            last = now
            frames += 1
            cv2.putText(annotated, f"{fps:4.1f} FPS  Iris: {len(boxes)}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

            if self.publish_raw and self.pub_image.get_subscription_count():
                img = Image()
                img.header.stamp = stamp
                img.header.frame_id = self.frame_id
                img.height, img.width = annotated.shape[:2]
                img.encoding = "bgr8"
                img.step = img.width * 3
                img.data = annotated.tobytes()
                self.pub_image.publish(img)

            if self.publish_compressed and self.pub_jpeg.get_subscription_count():
                ok, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
                if ok:
                    cimg = CompressedImage()
                    cimg.header.stamp = stamp
                    cimg.header.frame_id = self.frame_id
                    cimg.format = "jpeg"
                    cimg.data = jpeg.tobytes()
                    self.pub_jpeg.publish(cimg)

            if self.out_pipe is not None:
                self.src.emit("push-buffer", Gst.Buffer.new_wrapped(annotated.tobytes()))

            if frames % 30 == 0:
                self.get_logger().info(f"frames={frames} fps={fps:.1f} detections={len(boxes)}")

    def stop(self):
        self.running = False
        self.thread.join(timeout=3)
        self.cap_pipe.set_state(Gst.State.NULL)
        if self.out_pipe is not None:
            self.out_pipe.set_state(Gst.State.NULL)


def main():
    # Handle Ctrl+C / kill ourselves: the capture thread must stop before the ROS context goes away.
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    node = IrisDetector()
    try:
        # spin_once with a timeout: the node has no callbacks, so spin() would never wake up for signals.
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.5)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.stop()
        node.destroy_node()
        rclpy.try_shutdown()
        # Interpreter teardown segfaults (ncnn/GStreamer destructors); the kernel releases camera and DRM anyway.
        os._exit(0)


if __name__ == "__main__":
    main()
