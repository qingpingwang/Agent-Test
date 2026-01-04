#!/bin/bash

# ==================== 服务状态检查脚本 ====================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PID_FILE="server.pid"

if [ ! -f "$PID_FILE" ]; then
    echo -e "${RED}✗ 服务未运行${NC}"
    exit 1
fi

PID=$(cat "$PID_FILE")

if ps -p $PID > /dev/null 2>&1; then
    echo -e "${GREEN}✓ 服务正在运行${NC}"
    echo -e "${GREEN}  PID: $PID${NC}"
    echo -e "${GREEN}  启动时间: $(ps -o lstart= -p $PID)${NC}"
    echo -e "${GREEN}  内存使用: $(ps -o rss= -p $PID | awk '{printf "%.2f MB", $1/1024}')${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠ PID 文件存在但进程不存在${NC}"
    exit 1
fi

