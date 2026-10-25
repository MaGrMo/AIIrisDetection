# IrisProjectAI

Real-time Iris detection on a Raspberry Pi 5. Frames come from an imx219 camera, run through a YOLO11s model exported to NCNN, and the annotated video is sent straight to HDMI through KMS. No desktop or compositor is needed.

## Repository layout

```
models/
  best.pt                  # trained YOLO11s model (PyTorch), 1 class: Iris
  best320_ncnn_model/      # same model exported to NCNN, 320x320 input
pi/
  yolo_hdmi.py             # camera (libcamera) -> YOLO (NCNN) -> HDMI (kmssink)
  monitor.sh               # logs system state every 2 s (voltage, temp, CPU, memory)
  requirements.txt         # pip package versions tested on the Pi
ros/
  iris_detector_node.py    # ROS 2 node: camera -> YOLO -> video / detected / offset topics
  iris_tracker_node.py     # ROS 2 node: offset -> pan motor commands
  run_ros.sh               # starts both nodes
  README.md                # topics, parameters and how to run them
training/
  train.py                 # fine-tunes yolo11s.pt on the dataset (60 epochs, 640)
  create_data_yaml.py      # builds content/data.yaml from classes.txt
  camera.py                # desktop webcam test of models/best.pt
  runs/train-4/            # metrics, curves and sample batches of the final run
  predict/                 # model predictions on 20 dataset photos
```

## Training

The model is `yolo11s.pt` fine-tuned for 60 epochs at 640x640 on one class, `Iris`. Labels were made in Label Studio and exported as YOLO. Training ran on a Windows PC with an AMD GPU (ROCm). The dataset is not in this repository: `train.py` expects it in `training/content/`.

```bash
cd training
python create_data_yaml.py
python train.py
```

Final run (`training/runs/train-4`):

| Metric (validation) | Best epoch (59) | Last epoch (60) |
|---------------------|-----------------|-----------------|
| Precision           | 0.972           | 0.980           |
| Recall              | 1.000           | 1.000           |
| mAP50               | 0.995           | 0.995           |
| mAP50-95            | 0.783           | 0.780           |

`models/best.pt` is the checkpoint from epoch 59. Curves, the confusion matrix and validation predictions are in `training/runs/train-4/`.

## Performance

All runs used a Raspberry Pi 5 with the YOLO11s model (21.6 GFLOPs at 640) exported to NCNN, running on all 4 CPU cores. FPS is the end-to-end rate: capture, colour conversion, inference, drawing boxes, and HDMI output.

| Camera resolution | Model input | FPS    | Notes                                    |
|-------------------|-------------|--------|------------------------------------------|
| 640x480           | 320x320     | ~15    | fastest                                  |
| **800x600**       | **320x320** | **~11–12** | **recommended (default)**          |
| 640x480           | 640x480     | ~5.4   | no resize between camera and model       |
| 800x600           | 640x480     | ~4.2   |                                          |
| 800x600           | 800x608     | ~2.5   | 608 because sides must be multiples of 32 |
| 1280x720          | 864x480     | ~2.1   | CPU fully saturated                      |

Test with the default setup (800x600 camera, 320x320 model):

| Metric              | Value                              |
|---------------------|------------------------------------|
| Uninterrupted run   | 85 min, ~56,000 frames, no crash   |
| CPU temperature     | 45–60 °C (no thermal throttling)   |
| CPU clock           | mostly 2400 MHz                    |
| Process memory (RSS)| ~435 MB, stable (no leak)          |
| Undervoltage events | 6 in 85 min on a 5V/3A supply      |

The first test used a 1280x720 camera with a 640x640 NCNN model and ran at about 2 FPS. Lowering both the camera and the model resolution is what brought it to the numbers above.

## Setup on the Pi

```bash
mkdir -p ~/develop/yoko && cd ~/develop/yoko
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# copy pi/yolo_hdmi.py, pi/monitor.sh, ros/* and models/best320_ncnn_model here
```

The OS image (Yocto/Poky scarthgap) must include:
- GStreamer with `libcamerasrc`, `kmssink`, `videoconvert`, `appsrc` and `appsink`
- Mesa with the v3d/vc4 drivers
- PyGObject (`gi`)

The script loads `gi` from the system Python, because OpenCV from pip is built without GStreamer support.

## Usage

```bash
cd ~/develop/yoko
.venv/bin/python yolo_hdmi.py                          # 800x600 camera, 320 model, until Ctrl+C
.venv/bin/python yolo_hdmi.py --conf 0.4 --duration 60
```

| Option        | Default              | Description                                   |
|---------------|----------------------|-----------------------------------------------|
| `--model`     | `best320_ncnn_model` | NCNN model directory                          |
| `--width`     | `800`                | camera width                                  |
| `--height`    | `600`                | camera height                                 |
| `--fps`       | `30`                 | camera frame rate                             |
| `--imgsz`     | `320`                | model input, `H W` or one value for a square; must match the export size |
| `--conf`      | `0.5`                | detection confidence threshold                |
| `--connector` | `32`                 | DRM connector id (`modetest -M vc4 -c`)       |
| `--duration`  | `0`                  | seconds to run, `0` = until Ctrl+C            |

To use a different model input size, export the model at that size first:

```bash
.venv/bin/yolo export model=best.pt format=ncnn "imgsz=[480,640]"
.venv/bin/python yolo_hdmi.py --model best_ncnn_model --imgsz 480 640
```

## ROS 2 nodes

The same pipeline is also available as two ROS 2 (Jazzy) nodes. The detector publishes the annotated video, whether an Iris is detected, and its offset from the frame centre. The tracker turns that offset into pan motor commands. Start both with:

```bash
cd ~/develop/yoko && ./run_ros.sh
```

Topics, parameters and details are in [ros/README.md](ros/README.md).

## Known issues

- **libcamerasrc** only outputs the raw Bayer stream unless you set `stream-role=video-recording` and `format=NV12` explicitly.
