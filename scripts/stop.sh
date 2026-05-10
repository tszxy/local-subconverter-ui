#!/bin/zsh
set -eu

USER_ID="$(id -u)"

launchctl bootout "gui/$USER_ID/local.subconverter-ui" 2>/dev/null || true
launchctl bootout "gui/$USER_ID/local.subconverter" 2>/dev/null || true

echo "已停止本地订阅转换服务。"
