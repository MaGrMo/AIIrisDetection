# ROS 2 nodes

Two ROS 2 (Jazzy) nodes for the Raspberry Pi 5. The detector finds the Iris in the camera image. The tracker turns the detection into pan commands for the camera motor. Both are plain `rclpy` scripts, so colcon and custom interface packages are not needed.

```
ros/
  iris_detector_node.py    # camera -> YOLO -> video / detected / offset topics
  iris_tracker_node.py     # offset -> which way and how far to turn the pan motor (stdout)
  run_ros.sh               # starts both nodes, Ctrl+C stops both
```

## Setup on the Pi

The nodes run from the same folder as the model and the venv described in the [main README](../README.md#setup-on-the-pi):

```
~/develop/yoko/
  .venv/
  best320_ncnn_model/
  iris_detector_node.py
  iris_tracker_node.py
  run_ros.sh
```

ROS 2 Jazzy has to be installed in `/opt/ros/jazzy`. The detector runs in the venv, because it needs ultralytics and ncnn. The tracker only needs ROS, so it runs on the system `python3`.

## Running

Start both nodes with one command:

```bash
cd ~/develop/yoko
./run_ros.sh              # namespace /iris
NS=/robot ./run_ros.sh    # other namespace
```

`run_ros.sh` does the following:
1. Sources `/opt/ros/jazzy/setup.bash`.
2. Starts the detector in the background and writes its output to `detector.log`.
3. Waits for the model to load. If the detector exits, it prints the end of the log and stops.
4. Runs the tracker in the foreground, so its commands are printed to the terminal.
5. Stops both nodes on Ctrl+C.

Only one process can use the camera at a time. Stop `yolo_hdmi.py` or any other running detector first.

To run the nodes separately, use two terminals:

```bash
cd ~/develop/yoko && source /opt/ros/jazzy/setup.bash
.venv/bin/python iris_detector_node.py --ros-args -r __ns:=/iris   # terminal 1
python3 iris_tracker_node.py --ros-args -r __ns:=/iris            # terminal 2
```

## Detector: `iris_detector_node.py`

It reads frames from the camera (libcamera), runs the NCNN model, and publishes:

| Topic                              | Type                          | Content                                   |
|------------------------------------|-------------------------------|-------------------------------------------|
| `/iris/image_annotated`            | `sensor_msgs/Image` (bgr8)    | camera frame with boxes drawn             |
| `/iris/image_annotated/compressed` | `sensor_msgs/CompressedImage` | same frame as JPEG, ~135 KB/s             |
| `/iris/detected`                   | `std_msgs/Bool`               | `true` if an Iris is in the frame         |
| `/iris/offset`                     | `geometry_msgs/PointStamped`  | position of the most confident detection relative to the frame centre, published only when something is detected |

In `/iris/offset`:
- `point.x` goes from -1 (left edge) to +1 (right edge).
- `point.y` goes from -1 (bottom edge) to +1 (top edge).
- `point.z` is the detection confidence.

The annotated video also shows a cross at the frame centre, a line from the centre to the object, and the `dx`/`dy` values.

All topics publish at about 11 Hz with the default 800x600 camera and 320 model. The video topics use best-effort QoS, and frames are only encoded while someone is subscribed.

| Parameter            | Default              | Description                                  |
|----------------------|----------------------|----------------------------------------------|
| `model`              | `best320_ncnn_model` | NCNN model directory                         |
| `width`, `height`    | `800`, `600`         | camera resolution                            |
| `fps`                | `30`                 | camera frame rate                            |
| `imgsz`              | `[320]`              | model input, must match the export size      |
| `conf`               | `0.5`                | detection confidence threshold               |
| `frame_id`           | `camera`             | `frame_id` in message headers                |
| `publish_raw`        | `true`               | publish `image_annotated`                    |
| `publish_compressed` | `true`               | publish `image_annotated/compressed`         |
| `jpeg_quality`       | `70`                 | JPEG quality for the compressed topic        |
| `hdmi`               | `false`              | also send the annotated video to HDMI        |
| `connector`          | `32`                 | DRM connector id for HDMI                    |

Example: `.venv/bin/python iris_detector_node.py --ros-args -r __ns:=/iris -p conf:=0.4 -p hdmi:=true`

The node builds the `Image` message itself instead of using `cv_bridge`. The system `cv_bridge` is built against numpy 1.26, while the venv has numpy 2.x.

## Tracker: `iris_tracker_node.py`

It subscribes to `/iris/detected` and `/iris/offset` and prints, for every frame, which way and how far the pan motor should turn so that the camera centre points at the object:

```
RIGHT  4.45 deg
LEFT   1.69 deg
CENTER
STOP   no detection for 0.50 s
```

- The horizontal offset `x` is converted to an angle using the camera's horizontal field of view.
- Each step is `gain` × the angle, capped at `max_step_deg`. This keeps the motor from overshooting, because the camera image lags behind the motor.
- `CENTER` is printed when the object is within `tolerance_deg` of the centre.
- `STOP` is printed once when nothing has been detected for `lost_timeout` seconds.

| Parameter       | Default | Description                                         |
|-----------------|---------|-----------------------------------------------------|
| `hfov_deg`      | `62.2`  | camera horizontal field of view (imx219, standard lens) |
| `gain`          | `0.5`   | fraction of the angle to turn per frame             |
| `max_step_deg`  | `5.0`   | largest single step                                 |
| `tolerance_deg` | `2.0`   | below this the object counts as centred             |
| `lost_timeout`  | `0.5`   | seconds without a detection before `STOP`           |

There is no motor yet. To drive a real one, replace the `print` calls in `on_offset()` with the turn command, and the one in `check_lost()` with a stop command.
