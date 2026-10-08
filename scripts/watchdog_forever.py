#!/usr/bin/env python3
"""نگهبان دائمی پنل ققنوس — اگر سرویس بمیرد، دوباره بالا می‌آید و پایش را از سر می‌گیرد.

این اسکریپت برای اجرا روی یک هاست همیشه روشن است (VPS / Render / Railway / سرور خانگی).
روی Cloud Agent موقتی Cursor دوام ندارد؛ آن محیط با پایان چت خاموش می‌شود.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOST = os.environ.get("PHOENIX_HOST", "0.0.0.0")
PORT = int(os.environ.get("PHOENIX_PORT", "8080"))
TOP = os.environ.get("PHOENIX_TOP", "20")
INTERVAL = os.environ.get("PHOENIX_INTERVAL", "90")
SYMBOLS = os.environ.get("PHOENIX_SYMBOLS", "")  # خالی = top by volume
HEALTH = f"http://127.0.0.1:{PORT}/api/health"
START = f"http://127.0.0.1:{PORT}/api/start?top={TOP}&interval={INTERVAL}"
if SYMBOLS:
    START += f"&symbols={SYMBOLS}"
STATE = f"http://127.0.0.1:{PORT}/api/state"

CHECK_EVERY = int(os.environ.get("PHOENIX_CHECK_EVERY", "15"))
RESTART_DELAY = int(os.environ.get("PHOENIX_RESTART_DELAY", "3"))

_child: subprocess.Popen | None = None
_stop = False


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


def http_json(url: str, method: str = "GET", timeout: float = 10.0) -> dict | None:
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            import json

            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        log(f"http fail {method} {url}: {exc}")
        return None


def spawn() -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "phoenix.live_app:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]
    log(f"spawn: {' '.join(cmd)}")
    return subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def ensure_monitor() -> None:
    st = http_json(STATE)
    if not st:
        return
    if st.get("running"):
        return
    log("monitor not running → start")
    http_json(START, method="POST", timeout=20.0)


def healthy() -> bool:
    h = http_json(HEALTH, timeout=5.0)
    return bool(h and h.get("ok"))


def shutdown(*_args) -> None:
    global _stop
    _stop = True
    log("shutdown signal")
    if _child and _child.poll() is None:
        _child.terminate()


def main() -> int:
    global _child
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    log("ققنوس watchdog شروع شد — پایش دائمی با خودترمیم")
    log(f"port={PORT} top={TOP} interval={INTERVAL}s symbols={SYMBOLS or 'TOP_VOLUME'}")

    while not _stop:
        if _child is None or _child.poll() is not None:
            code = None if _child is None else _child.poll()
            if _child is not None:
                log(f"child exited code={code} → restart in {RESTART_DELAY}s")
                time.sleep(RESTART_DELAY)
            _child = spawn()
            # wait until health ok
            for _ in range(40):
                if _stop:
                    break
                if healthy():
                    log("health ok")
                    ensure_monitor()
                    break
                time.sleep(0.5)
            else:
                log("health timeout — kill and retry")
                if _child.poll() is None:
                    _child.kill()
                continue

        # periodic health + ensure monitor loop
        if not healthy():
            log("health lost — restart child")
            if _child.poll() is None:
                _child.terminate()
                try:
                    _child.wait(timeout=8)
                except Exception:  # noqa: BLE001
                    _child.kill()
            continue

        ensure_monitor()
        st = http_json(STATE)
        if st:
            s = st.get("summary") or {}
            log(
                f"alive cycle={st.get('cycle')} scanning={st.get('scanning')} "
                f"setups={s.get('setups')} watches={s.get('watches')}"
            )
        time.sleep(CHECK_EVERY)

    if _child and _child.poll() is None:
        _child.terminate()
    log("watchdog stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
