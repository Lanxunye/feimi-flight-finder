#!/bin/zsh
set -eu

script_dir="${0:A:h}"
project_dir="${script_dir:h}"
feimi_root="${FEIMI_DATA_DIR:-$HOME/Library/Application Support/Feimi}"
launch_agent_dir="${FEIMI_LAUNCH_AGENT_DIR:-$HOME/Library/LaunchAgents}"
node_bin="$(command -v node || true)"

if [[ -z "$node_bin" ]]; then
  echo "未找到 Node.js，请先安装 Node.js 22 或更高版本。" >&2
  exit 1
fi

node_dir="${node_bin:h}"
mkdir -p "$launch_agent_dir" "$feimi_root/logs" "$feimi_root/runtime-state" "$feimi_root/scripts"

for template in "$project_dir"/launchd/*.plist; do
  destination="$launch_agent_dir/${template:t}"
  /usr/bin/sed \
    -e "s|__FEIMI_ROOT__|$feimi_root|g" \
    -e "s|__NODE_BIN__|$node_bin|g" \
    -e "s|__NODE_DIR__|$node_dir|g" \
    "$template" > "$destination"
  /usr/bin/plutil -lint "$destination" >/dev/null
done

/bin/cp "$project_dir"/scripts/*.sh "$feimi_root/scripts/"
/bin/chmod 700 "$feimi_root/scripts"/*.sh
echo "飞觅 LaunchAgent 模板已安装到 $launch_agent_dir"
