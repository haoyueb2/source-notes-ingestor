#!/usr/bin/env bash
set -euo pipefail

vault_root="${1:-${OBSIDIAN_VAULT_PATH:-}}"
account_name="${2:-大魔王的后花园}"

if [ -z "${vault_root}" ]; then
  echo "usage: $0 <vault-path> [account-name]" >&2
  exit 1
fi

account_dir="$vault_root/Sources/WeChat/$account_name"
state_file="$vault_root/Sources/_state/wechat-$account_name.json"

echo "vault: $vault_root"
echo "account: $account_name"
echo

while true; do
  clear
  echo "time: $(date '+%F %T')"
  echo "vault: $vault_root"
  echo "account: $account_name"
  echo
  count="$(find "$account_dir" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')"
  echo "markdown files: $count"
  if [ -f "$state_file" ]; then
    echo
    echo "state:"
    tail -20 "$state_file"
  else
    echo
    echo "state: not created yet"
  fi
  sleep 5
done
