#!/bin/zsh
set -eu

# 自动定位仓库根目录（脚本所在目录的上一级），无需手填绝对路径
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_ID="$(id -u)"

# 运行期目录：放到用户目录而非 /tmp，避免重启被系统清理
RUN_DIR="${SUBUI_RUN_DIR:-$HOME/Library/Application Support/local-subconverter-ui}"
SC_DIR="$RUN_DIR/subconverter"
UI_DIR="$RUN_DIR/ui"
VENV_DIR="$RUN_DIR/venv"
PY="$VENV_DIR/bin/python3"

# 监听端口（可用环境变量覆盖）
SUBUI_PORT="${SUBUI_PORT:-25501}"

# 根据系统/架构选择 subconverter 二进制
SC_VER="v0.9.0"
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS/$ARCH" in
  Darwin/arm64) SC_ASSET="subconverter_darwinarm.tar.gz" ;;
  Darwin/x86_64) SC_ASSET="subconverter_darwin64.tar.gz" ;;
  Linux/x86_64) SC_ASSET="subconverter_linux64.tar.gz" ;;
  Linux/aarch64) SC_ASSET="subconverter_aarch64.tar.gz" ;;
  *) echo "未适配的系统/架构: $OS/$ARCH，请手动放置 subconverter 到 $SC_DIR/" >&2; SC_ASSET="" ;;
esac
SC_URL="https://github.com/tindy2013/subconverter/releases/download/$SC_VER/$SC_ASSET"

mkdir -p "$SC_DIR" "$UI_DIR"

# 优先复用仓库本地已有的 subconverter（常见于旧版本已下载过）
if [ ! -x "$SC_DIR/subconverter" ] && [ -x "$ROOT/subconverter/subconverter" ]; then
  echo "复用本地 subconverter..."
  cp -R "$ROOT/subconverter/." "$SC_DIR/"
fi

# 下载 subconverter（仅首次）
if [ ! -x "$SC_DIR/subconverter" ] && [ -n "$SC_ASSET" ]; then
  echo "下载 subconverter ($SC_ASSET)..."
  curl -L -o "$RUN_DIR/$SC_ASSET" "$SC_URL"
  tar -xzf "$RUN_DIR/$SC_ASSET" -C "$RUN_DIR"
fi

# 准备 Python 虚拟环境并安装依赖（解决系统 python3 没有 PyYAML 的问题）
if [ ! -x "$PY" ]; then
  echo "创建 Python 虚拟环境..."
  /usr/bin/python3 -m venv "$VENV_DIR"
fi
"$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
"$PY" -m pip install --quiet -r "$ROOT/requirements.txt"

# 同步界面与服务代码
cp "$ROOT/ui/index.html" "$UI_DIR/index.html"
cp "$ROOT/ui/server.py" "$UI_DIR/server.py"
chmod +x "$SC_DIR/subconverter" 2>/dev/null || true
xattr -cr "$SC_DIR" "$UI_DIR" 2>/dev/null || true

# 生成 launchd plist（用 venv 的 python，端口可配置）
SC_PLIST="$RUN_DIR/local.subconverter.plist"
UI_PLIST="$RUN_DIR/local.subconverter-ui.plist"

cat > "$SC_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.subconverter</string>
  <key>ProgramArguments</key>
  <array>
    <string>$SC_DIR/subconverter</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$SC_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$RUN_DIR/local.subconverter.log</string>
  <key>StandardErrorPath</key>
  <string>$RUN_DIR/local.subconverter.err.log</string>
</dict>
</plist>
PLIST

cat > "$UI_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.subconverter-ui</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$UI_DIR/server.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$UI_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>SUBUI_PORT</key>
    <string>$SUBUI_PORT</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$RUN_DIR/local.subconverter-ui.log</string>
  <key>StandardErrorPath</key>
  <string>$RUN_DIR/local.subconverter-ui.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$USER_ID/local.subconverter" 2>/dev/null || true
launchctl bootout "gui/$USER_ID/local.subconverter-ui" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$USER_ID" "$SC_PLIST"
launchctl bootstrap "gui/$USER_ID" "$UI_PLIST"

sleep 1
echo "转换服务: http://127.0.0.1:25500/version"
echo "网页界面: http://127.0.0.1:$SUBUI_PORT/"
