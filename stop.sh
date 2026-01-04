#!/bin/bash
# 停止服务

[ ! -f server.pid ] && echo "✗ 服务未运行" && exit 1
kill $(cat server.pid) 2>/dev/null && sleep 1 && rm -f server.pid && echo "✓ 服务已停止" || echo "✗ 停止失败"
