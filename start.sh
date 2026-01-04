#!/bin/bash
# 后台启动服务

[ -f server.pid ] && ps -p $(cat server.pid) >/dev/null 2>&1 && echo "✗ 服务已运行 (PID: $(cat server.pid))" && exit 1
mkdir -p logs
PYTHONIOENCODING=utf-8 nohup python server.py > logs/server.log 2>&1 & echo $! > server.pid
sleep 1
ps -p $(cat server.pid) >/dev/null 2>&1 && echo "✓ 服务已启动 (PID: $(cat server.pid))" || (echo "✗ 启动失败，查看 logs/server.log"; rm -f server.pid; exit 1)
