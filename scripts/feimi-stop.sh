#!/bin/zsh
set -u

USER_DOMAIN="gui/$(/usr/bin/id -u)"
FEIMI_DATA_DIR="${FEIMI_DATA_DIR:-$HOME/Library/Application Support/Feimi}"

/bin/launchctl bootout "$USER_DOMAIN/com.feimi.web" 2>/dev/null || true
/bin/launchctl bootout "$USER_DOMAIN/com.feimi.crawler" 2>/dev/null || true
/bin/launchctl bootout "$USER_DOMAIN/com.feimi.ctrip-browser" 2>/dev/null || true
/bin/launchctl bootout "$USER_DOMAIN/com.feimi.qunar-browser" 2>/dev/null || true
/bin/launchctl bootout "$USER_DOMAIN/com.feimi.meituan-browser" 2>/dev/null || true
/bin/launchctl bootout "$USER_DOMAIN/com.feimi.price-monitor" 2>/dev/null || true

# launchd stops the managed browser jobs.  These precise profile checks also
# clear any child Chrome process that may remain after its job has exited,
# without touching the user's normal Chrome session.
/bin/sleep 1
/usr/bin/pkill -f -- "--user-data-dir=$FEIMI_DATA_DIR/ctrip-chrome-profile" 2>/dev/null || true
/usr/bin/pkill -f -- "--user-data-dir=$FEIMI_DATA_DIR/qunar-chrome-profile" 2>/dev/null || true
/usr/bin/pkill -f -- "--user-data-dir=$FEIMI_DATA_DIR/meituan-chrome-profile" 2>/dev/null || true
