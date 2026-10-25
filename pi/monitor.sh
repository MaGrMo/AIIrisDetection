#!/bin/sh
# Logs system state every 2 s and syncs, so the last lines survive a crash/reboot.
LOG=~/develop/yoko/monitor.log
KLOG=~/develop/yoko/kernel.log
PIDFILE=~/develop/yoko/yolo_hdmi.pid

echo "=== boot $(date) uptime=$(cut -d' ' -f1 /proc/uptime)" >> "$LOG"
dmesg >> "$KLOG"
dmesg -w >> "$KLOG" 2>&1 &

while true; do
    up=$(cut -d' ' -f1 /proc/uptime)
    temp=$(( $(cat /sys/class/hwmon/hwmon0/temp1_input) / 1000 ))
    freq=$(( $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || echo 0) / 1000 ))
    lcrit=$(cat /sys/class/hwmon/hwmon3/in0_lcrit_alarm)
    uv=$(dmesg | grep -ci undervolt)
    load=$(cut -d' ' -f1 /proc/loadavg)
    memavail=$(( $(grep MemAvailable /proc/meminfo | tr -s ' ' | cut -d' ' -f2) / 1024 ))
    if kill -0 "$(cat $PIDFILE 2>/dev/null)" 2>/dev/null; then
        yolo=1
        rss=$(( $(grep VmRSS /proc/$(cat $PIDFILE)/status | tr -s ' ' | cut -d' ' -f2) / 1024 ))
    else
        yolo=0; rss=0
    fi
    fps=$(grep "frames=" ~/develop/yoko/yolo_hdmi.log 2>/dev/null | tail -n 1)
    echo "up=${up}s t=${temp}C f=${freq}MHz lcrit=$lcrit uv=$uv load=$load memavail=${memavail}MB yolo=$yolo rss=${rss}MB | $fps" >> "$LOG"
    sync
    sleep 2
done
