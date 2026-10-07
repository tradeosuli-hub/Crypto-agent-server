"""
ایجنت عیب‌یابی (Watchdog) — هر ۱۵ دقیقه در یک Workflow جداگانه.

۱) پایش: آخرین اجرای موفق اسکن/اطلاعات، شکست‌های پیاپی، تازگی حافظه و Pages
۲) تشخیص: لاگ شکست را می‌خواند و علت را دسته‌بندی می‌کند؛ تجربه‌های قبلی (incidents) را می‌بیند؛
   اگر «مغز» (Grok/OpenAI) در دسترس باشد، تحلیل ریشه و پیشنهاد اقدام می‌گیرد
۳) ترمیم: اجرای دوبارهٔ Workflow، کاهش بار، گزارش Issue برای خطای کد، هشدار تلگرام
۴) حافظه: هر رخداد با تشخیص و اقدام ثبت و در بهبود بعدی «حل‌شده» می‌شود
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import requests

from phoenix import brain

API = "https://api.github.com"
SCAN_WF = "phoenix-pages.yml"
INTEL_WF = "phoenix-intel.yml"
WATCHDOG_WF = "phoenix-watchdog.yml"

SCAN_EXPECTED_MIN = 10
SCAN_STALL_MIN = 35          # cron گیت‌هاب تا ~۱۵ دقیقه تأخیر طبیعی دارد
INTEL_STALL_MIN = 100
MEMORY_STALL_MIN = 45
REDISPATCH_COOLDOWN_MIN = 30
INCIDENTS_KEEP = 300

KIND_FA = {
    "scan_stalled": "اسکن متوقف شده (اجرای موفق تازه‌ای نیست)",
    "scan_failing": "اسکن پیاپی شکست می‌خورد",
    "intel_stalled": "ایجنت اطلاعات عقب افتاده",
    "memory_stalled": "حافظهٔ دائمی به‌روز نمی‌شود",
    "pages_stale": "صفحهٔ منتشرشده کهنه است",
    "binance_block": "مسدودشدن/قطع دادهٔ بایننس",
    "rate_limit": "محدودیت نرخ API",
    "pip_install": "خطای نصب وابستگی",
    "pages_disabled": "GitHub Pages فعال نیست",
    "memory_push": "رد شدن push حافظه",
    "code_error": "استثنای کد (Traceback)",
    "timeout": "اتمام زمان اجرا",
    "unknown": "نامشخص",
}


class GitHub:
    def __init__(self, token: str | None, repo: str | None):
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
        self.ok = bool(self.token and self.repo)

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    def get(self, path: str, **params: Any) -> Any:
        r = requests.get(f"{API}/repos/{self.repo}{path}", headers=self._h(), params=params, timeout=25)
        return r.json() if r.ok else None

    def runs(self, workflow_file: str, n: int = 12) -> list[dict[str, Any]]:
        data = self.get(f"/actions/workflows/{workflow_file}/runs", per_page=n) or {}
        out = []
        for r in data.get("workflow_runs", []):
            out.append({
                "id": r["id"], "status": r["status"], "conclusion": r["conclusion"], "event": r["event"],
                "created_at": r["created_at"], "updated_at": r["updated_at"], "url": r["html_url"],
                "branch": r.get("head_branch"),
            })
        return out

    def failed_log_excerpt(self, run_id: int, max_lines: int = 60) -> str:
        jobs = (self.get(f"/actions/runs/{run_id}/jobs") or {}).get("jobs", [])
        for job in jobs:
            if job.get("conclusion") != "failure":
                continue
            try:
                r = requests.get(f"{API}/repos/{self.repo}/actions/jobs/{job['id']}/logs", headers=self._h(),
                                 timeout=30, allow_redirects=True)
                if not r.ok:
                    continue
                lines = r.text.splitlines()
                hits = [ln for ln in lines if re.search(r"error|Error|Traceback|##\[error\]|failed|rejected|451|429|403", ln)]
                picked = hits[-max_lines:] if hits else lines[-max_lines:]
                return "\n".join(re.sub(r"^\S+\s", "", ln)[:300] for ln in picked)
            except Exception:  # noqa: BLE001
                continue
        return ""

    def dispatch(self, workflow_file: str, inputs: dict[str, str] | None = None, ref: str | None = None) -> bool:
        ref = ref or os.environ.get("GITHUB_REF_NAME") or "main"
        try:
            r = requests.post(f"{API}/repos/{self.repo}/actions/workflows/{workflow_file}/dispatches", headers=self._h(),
                              json={"ref": ref, "inputs": inputs or {}}, timeout=25)
            return r.status_code in (201, 204)
        except Exception:  # noqa: BLE001
            return False

    def upsert_issue(self, title: str, body: str, label: str = "phoenix-watchdog") -> str | None:
        try:
            q = self.get("/issues", state="open", labels=label, per_page=20) or []
            for it in q:
                if it.get("title") == title:
                    requests.post(f"{API}/repos/{self.repo}/issues/{it['number']}/comments", headers=self._h(),
                                  json={"body": body}, timeout=25)
                    return it.get("html_url")
            r = requests.post(f"{API}/repos/{self.repo}/issues", headers=self._h(),
                              json={"title": title, "body": body, "labels": [label]}, timeout=25)
            return r.json().get("html_url") if r.ok else None
        except Exception:  # noqa: BLE001
            return None

    def branch_age_min(self, branch: str) -> float | None:
        b = self.get(f"/branches/{branch}")
        try:
            ts = b["commit"]["commit"]["committer"]["date"]
            return (datetime.now(timezone.utc) - _ts(ts)).total_seconds() / 60
        except Exception:  # noqa: BLE001
            return None


def _ts(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def classify_log(excerpt: str) -> str:
    t = excerpt.lower()
    if "451" in t or "blocked at" in t or ("binance" in t and ("connectionerror" in t or "max retries" in t)):
        return "binance_block"
    if "429" in t or "too many requests" in t or "rate limit" in t:
        return "rate_limit"
    if "pip" in t and ("error" in t or "failed" in t) and "install" in t:
        return "pip_install"
    if "pages" in t and ("404" in t or "not found" in t or "has been enabled" in t):
        return "pages_disabled"
    if "memory persist failed" in t or ("push" in t and "rejected" in t):
        return "memory_push"
    if "traceback" in t or "exception" in t:
        return "code_error"
    if "timed out" in t or "timeout" in t or "exceeded the maximum execution time" in t:
        return "timeout"
    return "unknown"


def _age_min(iso: str | None) -> float | None:
    if not iso:
        return None
    return (datetime.now(timezone.utc) - _ts(iso)).total_seconds() / 60


def check_health(gh: GitHub, memory_data: dict[str, Any], pages_url: str | None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    scan_runs = gh.runs(SCAN_WF) if gh.ok else []
    intel_runs = gh.runs(INTEL_WF) if gh.ok else []
    checks: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []

    def last_success(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
        return next((r for r in runs if r["conclusion"] == "success"), None)

    def consecutive_failures(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in runs:
            if r["status"] != "completed":
                continue
            if r["conclusion"] == "failure":
                out.append(r)
            else:
                break
        return out

    # اسکن
    ls = last_success(scan_runs)
    age = _age_min(ls["created_at"]) if ls else None
    checks.append({"name": "scan_fresh", "fa": "آخرین اسکن موفق", "ok": age is not None and age <= SCAN_STALL_MIN,
                   "value": f"{age:.0f} دقیقه پیش" if age is not None else "هیچ", "url": ls["url"] if ls else None})
    if age is None or age > SCAN_STALL_MIN:
        problems.append({"kind": "scan_stalled", "runs": scan_runs[:3]})
    fails = consecutive_failures(scan_runs)
    checks.append({"name": "scan_failures", "fa": "شکست‌های پیاپی اسکن", "ok": len(fails) < 2, "value": str(len(fails)),
                   "url": fails[0]["url"] if fails else None})
    if len(fails) >= 2:
        problems.append({"kind": "scan_failing", "runs": fails[:3]})

    # اطلاعات
    li = last_success(intel_runs)
    iage = _age_min(li["created_at"]) if li else None
    intel_ts = (memory_data.get("intel") or {}).get("updated_at")
    mage = _age_min(intel_ts)
    checks.append({"name": "intel_fresh", "fa": "ایجنت اطلاعات", "ok": (mage is not None and mage <= INTEL_STALL_MIN) or (iage is not None and iage <= INTEL_STALL_MIN),
                   "value": f"{mage:.0f} دقیقه پیش" if mage is not None else ("هیچ" if iage is None else f"اجرا {iage:.0f} دقیقه پیش")})
    if intel_runs and (mage is None or mage > INTEL_STALL_MIN) and (iage is None or iage > INTEL_STALL_MIN):
        problems.append({"kind": "intel_stalled", "runs": intel_runs[:3]})

    # حافظه
    bage = gh.branch_age_min(os.environ.get("MEMORY_BRANCH", "phoenix-memory")) if gh.ok else None
    checks.append({"name": "memory_fresh", "fa": "حافظهٔ دائمی (phoenix-memory)", "ok": bage is not None and bage <= MEMORY_STALL_MIN,
                   "value": f"{bage:.0f} دقیقه پیش" if bage is not None else "ناموجود"})
    if bage is not None and bage > MEMORY_STALL_MIN and ls is not None:
        problems.append({"kind": "memory_stalled"})

    # Pages
    if pages_url:
        try:
            r = requests.get(f"{pages_url.rstrip('/')}/data/latest.json", timeout=15)
            page_ts = r.json().get("generated_at") if r.ok else None
            page_age = _age_min(page_ts)
            checks.append({"name": "pages_fresh", "fa": "صفحهٔ منتشرشده", "ok": page_age is not None and page_age <= SCAN_STALL_MIN,
                           "value": f"{page_age:.0f} دقیقه پیش" if page_age is not None else f"HTTP {r.status_code}"})
            if r.ok and page_age is not None and page_age > SCAN_STALL_MIN:
                problems.append({"kind": "pages_stale"})
        except Exception:  # noqa: BLE001
            checks.append({"name": "pages_fresh", "fa": "صفحهٔ منتشرشده", "ok": False, "value": "در دسترس نیست"})

    return {"checked_at": now.isoformat(), "checks": checks, "problems": problems,
            "runs": {"scan": scan_runs[:8], "intel": intel_runs[:5]}}


def diagnose(gh: GitHub, problem: dict[str, Any], past: list[dict[str, Any]]) -> dict[str, Any]:
    kind = problem["kind"]
    cause = kind
    excerpt = ""
    for r in problem.get("runs") or []:
        if r.get("conclusion") == "failure":
            excerpt = gh.failed_log_excerpt(r["id"]) if gh.ok else ""
            if excerpt:
                cause = classify_log(excerpt)
                break
    similar = [p for p in past if p.get("cause") == cause][-5:]
    recurrence = len([p for p in past if p.get("cause") == cause])
    diag = {
        "kind": kind, "kind_fa": KIND_FA.get(kind, kind), "cause": cause, "cause_fa": KIND_FA.get(cause, cause),
        "log_excerpt": excerpt[-1500:], "recurrence": recurrence,
        "experience_fa": (f"این علت {recurrence} بار قبلاً دیده شده؛ آخرین اقدام: {similar[-1].get('action_fa')}"
                          if similar else "اولین بار است"),
    }
    if brain.available():
        res = brain.ask_json(
            "تو مهندس نگهبان یک سامانهٔ معاملاتی روی GitHub Actions هستی. با توجه به مشکل، لاگ و تجربه‌های قبلی، "
            "ریشهٔ احتمالی و بهترین اقدام فوری را به فارسی و کوتاه بده. فقط JSON: "
            "{\"root_cause_fa\": ..., \"action_fa\": ..., \"confidence\": 0..1, \"needs_human\": true/false}",
            f"مشکل: {kind}\nدسته‌بندی قاعده‌محور: {cause}\nلاگ:\n{excerpt[-2500:]}\nتجربه‌ها: {[s.get('summary_fa') for s in similar]}",
            max_tokens=500,
        )
        if res:
            diag["brain"] = {k: res.get(k) for k in ("root_cause_fa", "action_fa", "confidence", "needs_human")}
    return diag


def remediate(gh: GitHub, diag: dict[str, Any], past: list[dict[str, Any]]) -> dict[str, Any]:
    """اقدام خودکارِ امن. هرگز کد را عوض نمی‌کند؛ برای خطای کد Issue باز می‌کند."""
    cause, kind = diag["cause"], diag["kind"]
    now = datetime.now(timezone.utc)
    recent_dispatch = [p for p in past if p.get("action") == "redispatch" and
                       _age_min(p.get("ts")) is not None and _age_min(p.get("ts")) < REDISPATCH_COOLDOWN_MIN]
    action, action_fa, url = "none", "—", None

    if kind in ("scan_stalled", "scan_failing", "pages_stale", "memory_stalled") and cause in (
            "scan_stalled", "scan_failing", "pages_stale", "memory_stalled", "binance_block", "timeout", "memory_push", "unknown"):
        if recent_dispatch:
            action, action_fa = "wait", f"اجرای مجدد اخیراً زده شده ({len(recent_dispatch)})؛ منتظر نتیجه"
        elif gh.ok and gh.dispatch(SCAN_WF):
            action, action_fa = "redispatch", "اجرای دوبارهٔ Workflow اسکن زده شد"
    elif cause == "rate_limit":
        if gh.ok and not recent_dispatch and gh.dispatch(SCAN_WF, {"top": "15"}):
            action, action_fa = "redispatch", "اجرای مجدد با نصف بار (۱۵ ارز) برای عبور از محدودیت نرخ"
    elif kind == "intel_stalled":
        if gh.ok and not recent_dispatch and gh.dispatch(INTEL_WF):
            action, action_fa = "redispatch", "اجرای دوبارهٔ ایجنت اطلاعات"
    if cause == "pages_disabled":
        action, action_fa = "human", "Settings → Pages → Source: GitHub Actions (فقط صاحب ریپو)"
    if cause in ("code_error", "pip_install") or (diag.get("brain") or {}).get("needs_human"):
        title = f"[watchdog] {KIND_FA.get(cause, cause)} — {kind}"
        body = (f"**زمان:** {now.isoformat()}\n**تشخیص:** {diag.get('cause_fa')}\n**تجربه:** {diag.get('experience_fa')}\n\n"
                f"**مغز:** {diag.get('brain')}\n\n```\n{diag.get('log_excerpt','')[-1500:]}\n```")
        url = gh.upsert_issue(title, body) if gh.ok else None
        action = "issue" if url else action
        action_fa = ("گزارش Issue برای بررسی کد ثبت شد" if url else action_fa)
    return {"action": action, "action_fa": action_fa, "url": url, "ts": now.isoformat()}


def severity_of(kind: str, cause: str, recurrence: int) -> str:
    if cause in ("code_error", "pip_install") or kind == "scan_failing" or recurrence >= 3:
        return "high"
    if kind in ("scan_stalled", "memory_stalled"):
        return "medium"
    return "low"


def run(gh: GitHub, memory_data: dict[str, Any], pages_url: str | None) -> dict[str, Any]:
    incidents: list[dict[str, Any]] = memory_data.setdefault("incidents", [])
    health = check_health(gh, memory_data, pages_url)
    open_inc = [i for i in incidents if not i.get("resolved_at")]
    new_incidents: list[dict[str, Any]] = []
    active_kinds = {p["kind"] for p in health["problems"]}

    # رخدادهای باز که دیگر مشکل ندارند → حل‌شده (تجربهٔ موفق)
    for inc in open_inc:
        if inc["kind"] not in active_kinds:
            inc["resolved_at"] = health["checked_at"]
            inc["resolution_fa"] = f"برطرف شد پس از اقدام «{inc.get('action_fa')}»"

    for p in health["problems"]:
        existing = next((i for i in open_inc if i["kind"] == p["kind"] and not i.get("resolved_at")), None)
        diag = diagnose(gh, p, incidents)
        if existing:
            # تشدید: اگر همچنان باز است و زمان کافی گذشته، دوباره اقدام
            existing["checks"] = int(existing.get("checks", 1)) + 1
            if _age_min(existing.get("last_action_ts")) is None or _age_min(existing.get("last_action_ts")) > REDISPATCH_COOLDOWN_MIN:
                rem = remediate(gh, diag, incidents)
                existing.update({"action": rem["action"], "action_fa": rem["action_fa"], "url": rem["url"] or existing.get("url"),
                                 "last_action_ts": rem["ts"], "escalations": int(existing.get("escalations", 0)) + 1})
                existing["severity"] = "high" if existing["escalations"] >= 2 else existing.get("severity", "medium")
            continue
        rem = remediate(gh, diag, incidents)
        inc = {
            "id": "I" + health["checked_at"][:16].replace("-", "").replace(":", "").replace("T", ""),
            "ts": health["checked_at"], "kind": p["kind"], "kind_fa": KIND_FA.get(p["kind"], p["kind"]),
            "cause": diag["cause"], "cause_fa": diag["cause_fa"], "severity": severity_of(p["kind"], diag["cause"], diag["recurrence"]),
            "summary_fa": f"{KIND_FA.get(p['kind'], p['kind'])} · علت: {diag['cause_fa']} · {diag['experience_fa']}",
            "brain": diag.get("brain"), "log_excerpt": diag.get("log_excerpt", "")[-800:],
            "action": rem["action"], "action_fa": rem["action_fa"], "url": rem["url"] or (p.get("runs") or [{}])[0].get("url"),
            "last_action_ts": rem["ts"], "checks": 1, "escalations": 0, "resolved_at": None,
        }
        incidents.append(inc)
        new_incidents.append(inc)

    memory_data["incidents"] = incidents[-INCIDENTS_KEEP:]
    health["open_incidents"] = [i for i in memory_data["incidents"] if not i.get("resolved_at")]
    health["new_incidents"] = new_incidents
    health["brain"] = brain.provider()
    return health
