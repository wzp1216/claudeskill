#!/bin/bash
# check-oa 每日定时执行脚本（crontab: 30 7 * * * 每天 7:30）
# 以无头模式运行 /check-oa，日志写入 /media/data/AAAwork/claude/check-oa/logs/
export PATH=/usr/local/bin:/usr/bin:/bin:/home/wzp/.local/bin
export HOME=/home/wzp
# 浏览器所需 display（与 .mcp.json 中 chrome-devtools 配置一致）
export DISPLAY=:1
export XAUTHORITY=/run/user/1000/gdm/Xauthority

LOG_DIR=/media/data/AAAwork/claude/check-oa/logs
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y%m%d-%H%M).log"

cd /media/data/AAAwork || { echo "无法进入 /media/data/AAAwork" >> "$LOG"; exit 1; }
echo "=== check-oa 定时执行开始 $(date '+%F %T') ===" >> "$LOG"
# 30 分钟超时保护；--dangerously-skip-permissions 供无头模式全自动运行（本机自用技能）
timeout 1800 claude -p "/check-oa" --dangerously-skip-permissions >> "$LOG" 2>&1
echo "=== check-oa 定时执行结束 $(date '+%F %T')，退出码 $? ===" >> "$LOG"
