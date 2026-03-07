#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

echo "== Worktrees =="
git worktree list

echo
echo "== Branch Heads =="
for dir in \
  "$repo_root" \
  "${repo_root}-zhihu" \
  "${repo_root}-wechat"
do
  if [ -d "$dir/.git" ] || git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf '%s\n' "[$dir]"
    git -C "$dir" branch --show-current
    git -C "$dir" log --oneline -1
    echo
  fi
done

echo "== Demo Vault =="
if [ -d "$repo_root/demo-vault/Sources" ]; then
  find "$repo_root/demo-vault/Sources" -type f | sed "s|$repo_root/||" | sort
else
  echo "demo-vault not materialized"
fi
