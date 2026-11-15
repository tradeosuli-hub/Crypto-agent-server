#!/usr/bin/env bash
# حلقهٔ خودگردان روی همین شاخه — بدون cron، بدون مرج به main.
#
# cron گیت‌هاب فقط روی شاخهٔ پیش‌فرض کار می‌کند؛ ما نمی‌خواهیم چیزی به main برود.
# پس هر Workflow در پایانِ هر اجرا، اجرای بعدیِ خودش را روی همین شاخه dispatch می‌کند
# و اجرای بعدی با ورودی delay_min به اندازهٔ لازم صبر می‌کند. ریپو عمومی است → دقیقهٔ Actions رایگان است.
#
#   loop.sh self   <workflow.yml> <delay_min>   → زنجیرهٔ خودم را ادامه بده (اگر جانشینی در صف نیست)
#   loop.sh ensure <workflow.yml>               → اگر حلقهٔ آن Workflow مرده (هیچ اجرای فعال/در صف ندارد) آن را زنده کن
#
# ایمنی در برابر زنجیرهٔ تکراری:
#   self   → فقط اگر «جانشینِ هنوز شروع‌نشده‌ای» (queued/waiting/pending) وجود نداشته باشد dispatch می‌کنیم.
#            اجرای in_progress دیگر شمرده نمی‌شود: با concurrency.group فقط یکی می‌دود، پس in_progressِ غیر از خودمان
#            یا اجرای تازه‌تمام‌شده‌ای است که API هنوز به‌روز نکرده، یا دوقلویی که پشت سر ما می‌دود و خودش جانشین می‌سازد.
#            (درس ۱۱ نوامبر: دو دوقلو همدیگر را «جانشین» دیدند و هیچ‌کدام dispatch نکردند → حلقه مرد.)
#   ensure → اگر هیچ اجرای فعال/در صفی (هر وضعیتی) نباشد، حلقه مرده است → زنده کن.
# concurrency.group هر Workflow لایهٔ دوم است: دو زنجیره هم‌زمان نمی‌توانند بدوند؛ دوقلوی اضافی فقط یک نوبت پشت‌سرهم می‌دود.
set -euo pipefail

MODE="${1:-}"; WF="${2:-}"; DELAY="${3:-0}"
REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY}"
REF="${GITHUB_REF_NAME:?GITHUB_REF_NAME}"
SELF_ID="${GITHUB_RUN_ID:-0}"
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

count_runs() {
  # اجراهای این Workflow روی این شاخه در وضعیت‌های داده‌شده (به‌جز اجرای فعلی)
  local total=0 st
  for st in "$@"; do
    local n
    n="$(gh api "repos/$REPO/actions/workflows/$WF/runs?branch=$REF&status=$st&per_page=10" \
          --jq "[.workflow_runs[] | select(.id != $SELF_ID)] | length" 2>/dev/null || echo 0)"
    total=$((total + ${n:-0}))
  done
  echo "$total"
}

pending_runs() { count_runs queued waiting pending requested; }
active_runs()  { count_runs queued in_progress waiting pending requested; }

dispatch() {
  local delay="$1" tries=0
  until gh api -X POST "repos/$REPO/actions/workflows/$WF/dispatches" -f ref="$REF" -f "inputs[delay_min]=$delay" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -ge 4 ]; then echo "loop: dispatch $WF failed after $tries tries"; return 1; fi
    sleep $((tries * 5))
  done
  echo "loop: dispatched $WF on $REF (delay ${delay}m)"
}

case "$MODE" in
  self)
    if [ "$(pending_runs)" -gt 0 ]; then
      echo "loop: $WF already has a successor queued — not dispatching again"
    else
      dispatch "$DELAY"
    fi
    ;;
  ensure)
    if [ "$(active_runs)" -gt 0 ]; then
      echo "loop: $WF alive"
    else
      echo "loop: $WF loop is dead → reviving now"
      dispatch 0
    fi
    ;;
  *)
    echo "usage: loop.sh self|ensure <workflow.yml> [delay_min]" >&2; exit 2 ;;
esac
