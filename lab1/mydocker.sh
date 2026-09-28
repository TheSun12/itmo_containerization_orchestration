#!/bin/bash

sudo mkdir -p /sys/fs/cgroup/lab1docker
echo "+memory +cpu +pids" | sudo tee /sys/fs/cgroup/cgroup.subtree_control
echo 50M | sudo tee /sys/fs/cgroup/lab1docker/memory.max
echo "100000 50000" | sudo tee /sys/fs/cgroup/lab1docker/cpu.max
echo 5 | sudo tee /sys/fs/cgroup/lab1docker/pids.max

unshare --pid --mount --uts --ipc --user --map-root-user --fork \
setpriv --bounding-set=-all --inh-caps=-all --ambient-caps=-all /home/taisiya/lab1/venv/bin/python3 seccomp-filter.py

sleep 3

PYTHON_PID=$(pgrep -f "seccomp-filter.py" | head -n1)
echo "$PYTHON_PID" | sudo tee /sys/fs/cgroup/lab1docker/cgroup.procs
echo "OK: сервис PID=$PYTHON_PID"
