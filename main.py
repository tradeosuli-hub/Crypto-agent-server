#!/usr/bin/env python3
"""CLI + API پنل سیگنال‌دهی ققنوس (متد حمید v3)."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from phoenix.panel import PhoenixPanel, print_summary_fa, save_cycle  # noqa: E402
from strategies.hamid_method import SPEC, gates, prompt_path  # noqa: E402


def cmd_scan(args: argparse.Namespace) -> int:
    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    panel = PhoenixPanel(symbols=symbols, top_n=None if symbols else args.top, workers=args.workers)
    print(f"متد حمید {SPEC['version']} · اسکن {len(panel.symbols)} ارز · قوانین یکسان برای همه")
    summary = panel.run_cycle()
    path = save_cycle(summary, args.out)
    print_summary_fa(summary)
    print(f"ذخیره شد: {path}")
    # compact stdout json path
    compact = {
        "setups": summary["setups"],
        "watches": summary["watches"],
        "signals": summary["signals"],
        "watch_list": summary["watch_list"][:20],
        "dominance": summary["dominance"],
        "artifact": path,
    }
    if args.json:
        print(json.dumps(compact, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_gates(_: argparse.Namespace) -> int:
    print(json.dumps(gates(), ensure_ascii=False, indent=2))
    print("prompt:", prompt_path())
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    from phoenix.live_app import app

    print(f"پنل مستقل ققنوس · http://{args.host}:{args.port}")
    print("این سرویس به هیچ پنل دیگری وصل نیست.")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    """داشبورد لایو مستقل — فقط همین پنل."""
    return cmd_serve(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="پنل سیگنال‌دهی ققنوس — متد حمید v3")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="اسکن ارزها با قوانین یکسان")
    s.add_argument("--top", type=int, default=30, help="تعداد ارز برتر از نظر حجم")
    s.add_argument("--symbols", type=str, default=None, help="لیست نمادها با کاما، مثلاً BTCUSDT,ETHUSDT")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--out", type=str, default=None)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_scan)

    g = sub.add_parser("gates", help="نمایش گیت‌های سخت متد")
    g.set_defaults(func=cmd_gates)

    sv = sub.add_parser("serve", help="داشبورد لایو مستقل در مرورگر")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8080)
    sv.set_defaults(func=cmd_serve)

    lv = sub.add_parser("live", help="همان serve — داشبورد لایو")
    lv.add_argument("--host", default="0.0.0.0")
    lv.add_argument("--port", type=int, default=8080)
    lv.set_defaults(func=cmd_live)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
