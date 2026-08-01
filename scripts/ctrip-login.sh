#!/bin/zsh
set -u

USER_DOMAIN="gui/$(/usr/bin/id -u)"
AGENT_PLIST="$HOME/Library/LaunchAgents/com.feimi.ctrip-browser.plist"

if ! /bin/launchctl print "$USER_DOMAIN/com.feimi.ctrip-browser" >/dev/null 2>&1; then
  /bin/launchctl bootstrap "$USER_DOMAIN" "$AGENT_PLIST" 2>/dev/null || true
fi
/bin/launchctl kickstart "$USER_DOMAIN/com.feimi.ctrip-browser" >/dev/null 2>&1 || true
/bin/sleep 2
/usr/bin/open -a "Google Chrome"
/usr/bin/osascript -e 'display dialog "请在携程专用 Chrome 窗口完成登录或验证码。登录成功后保持该窗口开启，飞觅只会读取航班搜索响应，不会保存你的账号密码。" buttons {"好"} default button "好" with icon note'
