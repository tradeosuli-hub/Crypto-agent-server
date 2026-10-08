#!/usr/bin/env bash
# حافظهٔ دائمی مشترک روی شاخهٔ phoenix-memory — چند Workflow هم‌زمان، بدون پاک‌کردن فایل‌های هم.
#
#   memory_sync.sh restore <dir>                 → کل شاخه را در <dir> می‌آورد (یا خالی می‌سازد)
#   memory_sync.sh persist <dir> <file> [file…]  → فقط فایل‌های نام‌برده را روی آخرین نسخهٔ شاخه می‌نشاند و push می‌کند
#
# persist هرگز force نمی‌کند: fetch تازه → کپی فایل‌های خودمان → commit → push؛ در صورت رد شدن تا ۵ بار تکرار.
set -euo pipefail

MODE="${1:-}"; DIR="${2:-memory}"; shift 2 || true
BRANCH="${MEMORY_BRANCH:-phoenix-memory}"
REPO_URL="${MEMORY_REPO_URL:-https://x-access-token:${GITHUB_TOKEN:-}@github.com/${GITHUB_REPOSITORY:-}.git}"
WORK="$(mktemp -d)"

clone_branch() {
  rm -rf "$WORK"; mkdir -p "$WORK"
  if git clone -q --depth=1 --branch "$BRANCH" "$REPO_URL" "$WORK" 2>/dev/null; then
    return 0
  fi
  git init -q -b "$BRANCH" "$WORK"
  return 1
}

case "$MODE" in
  restore)
    mkdir -p "$DIR"
    if clone_branch; then
      rsync -a --exclude .git "$WORK/" "$DIR/"
      echo "memory restored: $(ls "$DIR" | tr '\n' ' ')"
    else
      echo "memory branch not found — starting empty"
    fi
    ;;
  persist)
    [ "$#" -gt 0 ] || { echo "persist: no files given"; exit 0; }
    for attempt in 1 2 3 4 5; do
      clone_branch || true
      for f in "$@"; do
        if [ -e "$DIR/$f" ]; then
          mkdir -p "$WORK/$(dirname "$f")"
          cp -r "$DIR/$f" "$WORK/$f"
        fi
      done
      (
        cd "$WORK"
        git config user.name "phoenix-org"
        git config user.email "phoenix-org@users.noreply.github.com"
        git add -A
        if git diff --cached --quiet; then
          echo "memory: nothing changed"; exit 0
        fi
        git commit -q -m "memory(${GITHUB_WORKFLOW:-local}): $(date -u +%Y-%m-%dT%H:%M:%SZ) [$*]"
        git push -q "$REPO_URL" "HEAD:refs/heads/$BRANCH"
      ) && { echo "memory persisted (attempt $attempt)"; exit 0; }
      echo "push rejected — retry $attempt"; sleep $((attempt * 3))
    done
    echo "::warning::memory persist failed after retries"; exit 0
    ;;
  *)
    echo "usage: $0 restore|persist <dir> [files…]"; exit 2 ;;
esac
