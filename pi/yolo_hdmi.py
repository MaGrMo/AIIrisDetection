#!/usr/bin/env python3
"""Camera (libcamera) -> YOLO (NCNN) -> HDMI (kmssink).

Run from the venv:
    .venv/bin/python yolo_hdmi.py
    .venv/bin/python yolo_hdmi.py --conf 0.4 --duration 30
"""
import argparse
import os
import signal
import sys
import time

# Hide libcamera's INFO lines, keep warnings and errors.
os.environ.setdefault("LIBCAMERA_LOG_LEVELS", "*:WARN")

# PyGObject (gi) comes from the system; append so the venv's numpy/cv2 still win.
sys.path.append("/usr/lib/python3.12/site-packages")

import cv2
import gi
import numpy as np

gi.require_version("Gst", "1.0")
from gi.repository import Gst
from ultralytics import YOLO


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="best320_ncnn_model")
    p.add_argument("--width", type=int, default=800)
    p.add_argument("--height", type=int, default=600)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--imgsz", type=int, nargs="+", default=[320],
                   help="H W (or one value for square); must match the size the NCNN model was exported with")
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--connector", type=int, default=32, help="DRM connector id (modetest -M vc4 -c)")
    p.add_argument("--duration", type=float, default=0, help="seconds to run, 0 = until Ctrl+C")
    return p.parse_args()


def main():
    args = parse_args()
    Gst.init(None)

    caps = f"video/x-raw,format=BGR,width={args.width},height={args.height},framerate={args.fps}/1"
    cap_pipe = Gst.parse_launch(
        # Without an explicit role and format, libcamerasrc only offers the raw Bayer stream.
        f"libcamerasrc src::stream-role=video-recording "
        f"! video/x-raw,format=NV12,width={args.width},height={args.height},framerate={args.fps}/1 "
        f"! videoconvert ! {caps} ! appsink name=sink max-buffers=1 drop=true sync=false"
    )
    out_pipe = Gst.parse_launch(
        f"appsrc name=src is-live=true do-timestamp=true format=time caps={caps} "
        f"! videoconvert ! kmssink connector-id={args.connector} sync=false"
    )
    sink = cap_pipe.get_by_name("sink")
    src = out_pipe.get_by_name("src")

    model = YOLO(args.model, task="detect")

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    cap_pipe.set_state(Gst.State.PLAYING)
    out_pipe.set_state(Gst.State.PLAYING)

    start = time.time()
    frames = 0
    fps = 0.0
    last = start
    try:
        while running:
            if args.duration and time.time() - start > args.duration:
                break
            sample = sink.emit("try-pull-sample", Gst.SECOND)
            if sample is None:
                print("no frame from camera", file=sys.stderr)
                continue

            buf = sample.get_buffer()
            ok, info = buf.map(Gst.MapFlags.READ)
            if not ok:
                continue
            frame = np.frombuffer(info.data, np.uint8).reshape(args.height, args.width, 3).copy()
            buf.unmap(info)

            imgsz = args.imgsz[0] if len(args.imgsz) == 1 else tuple(args.imgsz)
            result = model(frame, imgsz=imgsz, conf=args.conf, verbose=False)[0]
            annotated = result.plot()

            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(now - last, 1e-6)) if frames else 0.0
            last = now
            frames += 1
            cv2.putText(annotated, f"{fps:4.1f} FPS  Iris: {len(result.boxes)}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

            src.emit("push-buffer", Gst.Buffer.new_wrapped(annotated.tobytes()))

            if frames % 30 == 0:
                print(f"frames={frames} fps={fps:.1f} detections={len(result.boxes)}", flush=True)
    finally:
        elapsed = time.time() - start
        print(f"done: {frames} frames in {elapsed:.1f}s ({frames / max(elapsed, 1e-6):.1f} FPS avg)", flush=True)
        cap_pipe.set_state(Gst.State.NULL)
        out_pipe.set_state(Gst.State.NULL)
        # Interpreter teardown segfaults (ncnn/GStreamer destructors); the kernel releases camera and DRM anyway.
        os._exit(0)


if __name__ == "__main__":
    main()
