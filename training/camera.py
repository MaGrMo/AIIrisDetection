import os

# MSMF hardware transforms make camera open take tens of seconds on Windows
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

import cv2
import numpy as np
from ultralytics import YOLO

CAMERA_INDEX = 0


def open_camera(index):
    # DirectShow opens much faster than the default MSMF backend; fall back if it fails
    for backend in (cv2.CAP_DSHOW, cv2.CAP_ANY):
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened() and cap.read()[0]:
            return cap
        cap.release()
    raise SystemExit(f"Camera {index} not available (is another app using it?)")


if __name__ == "__main__":
    print("Loading model...", flush=True)
    model = YOLO("../models/best.pt")

    # First GPU inference compiles ROCm kernels (~10+ s); do it before opening the camera
    print("Warming up GPU...", flush=True)
    model(np.zeros((480, 640, 3), dtype=np.uint8), device=0, verbose=False)

    print("Opening camera...", flush=True)
    cap = open_camera(CAMERA_INDEX)
    print("Running. Press q in the window to quit.", flush=True)

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Camera stopped sending frames", flush=True)
            break
        result = model(frame, device=0, verbose=False)[0]
        cv2.imshow("Iris detection (q to quit)", result.plot())
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
