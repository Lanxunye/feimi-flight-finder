#!/bin/zsh
set -u

CRAWLER_URL="http://127.0.0.1:8001"
WEB_URL="http://127.0.0.1:3000"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
FEIMI_DATA_DIR="$HOME/Library/Application Support/Feimi"
USER_DOMAIN="gui/$(/usr/bin/id -u)"

mkdir -p "$FEIMI_DATA_DIR/runtime-state" "$LAUNCH_AGENT_DIR"

ensure_agent() {
  local agent_label="$1"
  local agent_plist="$2"
  if ! /bin/launchctl print "$USER_DOMAIN/$agent_label" >/dev/null 2>&1; then
    /bin/launchctl bootstrap "$USER_DOMAIN" "$agent_plist"
  else
    /bin/launchctl kickstart "$USER_DOMAIN/$agent_label" >/dev/null 2>&1 || true
  fi
}

wait_for_url() {
  local target_url="$1"
  local attempts="$2"
  local index=0
  while (( index < attempts )); do
    if /usr/bin/curl -fsS --max-time 2 "$target_url" >/dev/null 2>&1; then
      return 0
    fi
    /bin/sleep 1
    (( index += 1 ))
  done
  return 1
}

ensure_agent "com.feimi.crawler" "$LAUNCH_AGENT_DIR/com.feimi.crawler.plist"
ensure_agent "com.feimi.web" "$LAUNCH_AGENT_DIR/com.feimi.web.plist"
ensure_agent "com.feimi.ctrip-browser" "$LAUNCH_AGENT_DIR/com.feimi.ctrip-browser.plist"
ensure_agent "com.feimi.price-monitor" "$LAUNCH_AGENT_DIR/com.feimi.price-monitor.plist"

if ! wait_for_url "$CRAWLER_URL/health" 25; then
  /usr/bin/osascript -e 'display dialog "实时抓取服务启动失败，请联系 Codex 检查。" buttons {"好"} default button "好" with icon stop'
  exit 1
fi

if ! wait_for_url "$WEB_URL" 25; then
  /usr/bin/osascript -e 'display dialog "飞觅网页启动失败，请联系 Codex 检查。" buttons {"好"} default button "好" with icon stop'
  exit 1
fi

/usr/bin/open "$WEB_URL"
