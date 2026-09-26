"""سرویس لایو کاملاً مستقل پنل ققنوس — هیچ وابستگی به پنل‌های دیگر ندارد."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from phoenix.panel import PhoenixPanel, save_cycle  # noqa: E402
from strategies.hamid_method import SPEC, gates  # noqa: E402

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


class LiveMonitor:
    """پایش پیوسته — فقط همین پنل، جدا از بقیه."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.scanning = False
        self.top_n = 15
        self.interval_sec = 90
        self.symbols: list[str] | None = None
        self.last_summary: dict[str, Any] | None = None
        self.progress: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.cycle = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.subscribers: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "ok": True,
                "isolated": True,
                "panel": "hamid_phoenix_standalone",
                "note_fa": "این پنل کاملاً جداست و هیچ پنل دیگری را تغییر نمی‌دهد",
                "method": SPEC["version"],
                "running": self.running,
                "scanning": self.scanning,
                "cycle": self.cycle,
                "top_n": self.top_n,
                "interval_sec": self.interval_sec,
                "symbols": self.symbols,
                "progress": list(self.progress)[-40:],
                "events": list(self.events)[-80:],
                "summary": self._compact(self.last_summary) if self.last_summary else None,
                "gates": gates(),
                "now": datetime.now(timezone.utc).isoformat(),
            }

    @staticmethod
    def _compact(summary: dict[str, Any] | None) -> dict[str, Any] | None:
        if not summary:
            return None
        results_light = []
        for r in summary.get("results") or []:
            results_light.append(
                {
                    "symbol": r.get("symbol"),
                    "verdict": r.get("verdict"),
                    "direction": r.get("direction"),
                    "score": r.get("score"),
                    "why_fa": (r.get("why_fa") or [])[:4],
                    "alarms": r.get("alarms"),
                    "geometry": r.get("geometry"),
                    "params": {
                        "score": (r.get("params") or {}).get("score"),
                        "visible": (r.get("params") or {}).get("visible"),
                        "passed_names": (r.get("params") or {}).get("passed_names"),
                        "failed_names": (r.get("params") or {}).get("failed_names"),
                        "blind_names": (r.get("params") or {}).get("blind_names"),
                    },
                    "trigger": r.get("trigger"),
                    "wall": r.get("wall"),
                }
            )
        return {
            "started_at": summary.get("started_at"),
            "finished_at": summary.get("finished_at"),
            "symbols_scanned": summary.get("symbols_scanned"),
            "setups": summary.get("setups"),
            "watches": summary.get("watches"),
            "dominance": summary.get("dominance"),
            "signals": summary.get("signals"),
            "watch_list": summary.get("watch_list"),
            "results": results_light,
        }

    def _push_event(self, kind: str, payload: dict[str, Any]) -> None:
        ev = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **payload,
        }
        with self.lock:
            self.events.append(ev)
            if len(self.events) > 200:
                self.events = self.events[-200:]
        self._broadcast({"type": "event", "event": ev})

    def _broadcast(self, msg: dict[str, Any]) -> None:
        if not self._loop:
            return
        data = json.dumps(msg, ensure_ascii=False, default=str)
        for q in list(self.subscribers):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, data)
            except Exception:  # noqa: BLE001
                pass

    def start(self, top_n: int = 15, interval_sec: int = 90, symbols: str | None = None) -> dict[str, Any]:
        with self.lock:
            if self.running:
                return self.snapshot()
            self.top_n = top_n
            self.interval_sec = max(30, interval_sec)
            self.symbols = [s.strip().upper() for s in symbols.split(",")] if symbols else None
            self.running = True
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop_scan, name="phoenix-live", daemon=True)
            self._thread.start()
        self._push_event("monitor_started", {"top_n": self.top_n, "interval_sec": self.interval_sec})
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        with self.lock:
            self.running = False
        self._push_event("monitor_stopped", {})
        return self.snapshot()

    def run_once(self) -> dict[str, Any]:
        self._do_cycle()
        return self.snapshot()

    def _loop_scan(self) -> None:
        while not self._stop.is_set():
            try:
                self._do_cycle()
            except Exception as exc:  # noqa: BLE001
                self._push_event("error", {"error": str(exc)})
            # wait interval, but wake on stop
            for _ in range(self.interval_sec):
                if self._stop.is_set():
                    break
                time.sleep(1)
        with self.lock:
            self.running = False
            self.scanning = False

    def _do_cycle(self) -> None:
        with self.lock:
            if self.scanning:
                return
            self.scanning = True
            self.progress = []
            self.cycle += 1
            cycle_no = self.cycle
        self._push_event("cycle_start", {"cycle": cycle_no})
        self._broadcast({"type": "snapshot", "data": self.snapshot()})

        def on_result(res: dict[str, Any]) -> None:
            item = {
                "symbol": res.get("symbol"),
                "verdict": res.get("verdict"),
                "direction": res.get("direction"),
                "why_fa": (res.get("why_fa") or [])[:2],
            }
            with self.lock:
                self.progress.append(item)
            self._push_event("symbol_done", item)
            self._broadcast({"type": "progress", "item": item, "cycle": cycle_no})

        panel = PhoenixPanel(
            symbols=self.symbols,
            top_n=None if self.symbols else self.top_n,
            workers=4,
            on_result=on_result,
        )
        summary = panel.run_cycle()
        path = save_cycle(summary)
        summary["artifact"] = path
        with self.lock:
            self.last_summary = summary
            self.scanning = False
        self._push_event(
            "cycle_done",
            {
                "cycle": cycle_no,
                "setups": summary.get("setups"),
                "watches": summary.get("watches"),
                "scanned": summary.get("symbols_scanned"),
            },
        )
        self._broadcast({"type": "snapshot", "data": self.snapshot()})


monitor = LiveMonitor()
app = FastAPI(
    title="Hamid Phoenix Standalone Live Panel",
    version=SPEC["version"],
    description="کاملاً جدا از هر پنل دیگر — فقط متد حمید v3",
)


@app.on_event("startup")
async def _startup() -> None:
    monitor._loop = asyncio.get_running_loop()


@app.get("/")
def index():
    path = os.path.join(WEB_DIR, "index.html")
    return FileResponse(path, media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "isolated": True,
        "panel": "hamid_phoenix_standalone",
        "touches_other_panels": False,
        "method": "hamid_method_v3",
        "version": SPEC["version"],
    }


@app.get("/api/state")
def state():
    return monitor.snapshot()


@app.post("/api/start")
def start(top: int = 12, interval: int = 90, symbols: str | None = None):
    return monitor.start(top_n=top, interval_sec=interval, symbols=symbols)


@app.post("/api/stop")
def stop():
    return monitor.stop()


@app.post("/api/scan-once")
def scan_once(top: int = 12, symbols: str | None = None):
    if monitor.scanning:
        return {"ok": False, "note_fa": "اسکن در حال اجراست", **monitor.snapshot()}
    if symbols:
        monitor.symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        monitor.top_n = max(len(monitor.symbols), 1)
    elif not monitor.symbols:
        monitor.top_n = top
    t = threading.Thread(target=monitor.run_once, daemon=True)
    t.start()
    return {"ok": True, "note_fa": "یک چرخه شروع شد", **monitor.snapshot()}


@app.get("/api/gates")
def api_gates():
    return gates()


@app.websocket("/ws")
async def ws_feed(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    monitor.subscribers.append(q)
    await ws.send_text(json.dumps({"type": "snapshot", "data": monitor.snapshot()}, ensure_ascii=False, default=str))
    try:
        while True:
            # also allow client ping
            try:
                msg = await asyncio.wait_for(q.get(), timeout=20.0)
                await ws.send_text(msg)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "ping", "ts": datetime.now(timezone.utc).isoformat()}))
    except WebSocketDisconnect:
        pass
    finally:
        if q in monitor.subscribers:
            monitor.subscribers.remove(q)


def create_app() -> FastAPI:
    return app
