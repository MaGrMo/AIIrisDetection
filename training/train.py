import torch
from ultralytics import YOLO

if __name__ == "__main__":
    # MIOpen fails to JIT-compile BatchNorm kernels on Windows ROCm (HIPRTC_ERROR_COMPILATION),
    # so use PyTorch's native HIP kernels instead
    torch.backends.cudnn.enabled = False

    model = YOLO("yolo11s.pt")
    model.train(data="content/data.yaml", epochs=60, imgsz=640, device=0)
