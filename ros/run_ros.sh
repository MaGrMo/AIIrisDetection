#!/bin/bash
# Starts both ROS 2 nodes: detector in the background (log in detector.log),
# tracker in the foreground. Ctrl+C stops both.
#
#   ./run_ros.sh              # namespace /iris
#   NS=/robot ./run_ros.sh    # other namespace

cd "$(dirname "$0")" || exit 1
source /opt/ros/jazzy/setup.bash

NS=${NS:-/iris}

.venv/bin/python iris_detector_node.py --ros-args -r __ns:="$NS" > detector.log 2>&1 < /dev/null &
DETECTOR=$!
trap 'kill -TERM $DETECTOR 2>/dev/null; wait $DETECTOR 2>/dev/null' EXIT

echo "detector started (pid $DETECTOR, log: detector.log), waiting for the model to load..."
for _ in $(seq 1 30); do
    grep -q "running: camera" detector.log 2>/dev/null && break
    kill -0 $DETECTOR 2>/dev/null || { echo "detector exited:"; tail -n 20 detector.log; exit 1; }
    sleep 1
done

python3 iris_tracker_node.py --ros-args -r __ns:="$NS"
