#!/bin/zsh
set -u

USER_DOMAIN="gui/$(/usr/bin/id -u)"
AGENT_PLIST="$HOME/Library/LaunchAgents/com.feimi.meituan-browser.plist"

if ! /bin/launchctl print "$USER_DOMAIN/com.feimi.meituan-browser" >/dev/null 2>&1; then
  /bin/launchctl bootstrap "$USER_DOMAIN" "$AGENT_PLIST" 2>/dev/null || true
fi
/bin/launchctl kickstart "$USER_DOMAIN/com.feimi.meituan-browser" >/dev/null 2>&1 || true
/bin/sleep 2
/usr/bin/open -a "Google Chrome"
/usr/bin/osascript -e 'display dialog "请在美团专用 Chrome 窗口完成人机验证并登录，然后进入机票频道、搜索一次任意国内机票并保持窗口开启。飞觅不会读取或保存你的账号密码。" buttons {"好"} default button "好" with icon note'
