#!/bin/zsh
set -eu

ROOT="/Users/zhang/Documents/Codex/2026-05-10/clash"
USER_ID="$(id -u)"
SUBCONVERTER_URL="https://github.com/tindy2013/subconverter/releases/download/v0.9.0/subconverter_darwinarm.tar.gz"

if [ ! -x "$ROOT/subconverter/subconverter" ]; then
  mkdir -p "$ROOT"
  curl -L -o "$ROOT/subconverter_darwinarm.tar.gz" "$SUBCONVERTER_URL"
  tar -xzf "$ROOT/subconverter_darwinarm.tar.gz" -C "$ROOT"
fi

rm -rf /tmp/local-subconverter /tmp/subconverter-ui
mkdir -p /tmp/local-subconverter /tmp/subconverter-ui

cp -R "$ROOT/subconverter/." /tmp/local-subconverter/
cp "$ROOT/ui/index.html" /tmp/subconverter-ui/index.html
cp "$ROOT/ui/server.py" /tmp/subconverter-ui/server.py
chmod +x /tmp/local-subconverter/subconverter
xattr -cr /tmp/local-subconverter /tmp/subconverter-ui 2>/dev/null || true

cat > /tmp/local.subconverter.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.subconverter</string>
  <key>ProgramArguments</key>
  <array>
    <string>/tmp/local-subconverter/subconverter</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/tmp/local-subconverter</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/local.subconverter.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/local.subconverter.err.log</string>
</dict>
</plist>
PLIST

cat > /tmp/local.subconverter-ui.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.subconverter-ui</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/tmp/subconverter-ui/server.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/tmp/subconverter-ui</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/local.subconverter-ui.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/local.subconverter-ui.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$USER_ID/local.subconverter" 2>/dev/null || true
launchctl bootout "gui/$USER_ID/local.subconverter-ui" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$USER_ID" /tmp/local.subconverter.plist
launchctl bootstrap "gui/$USER_ID" /tmp/local.subconverter-ui.plist

sleep 1
echo "转换服务: http://127.0.0.1:25500/version"
echo "网页界面: http://127.0.0.1:25501/"
