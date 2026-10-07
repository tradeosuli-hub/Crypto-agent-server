# پنل مستقل ققنوس — متد حمید نسخهٔ ۳

> **جداسازی:** این پنل کاملاً مستقل است و هیچ پنل سیگنال دیگری در گیت‌هاب را تغییر نمی‌دهد.
> جزئیات: [`STANDALONE.md`](STANDALONE.md)

قوانین برای **همهٔ ارزها یکسان** است. سولانا/کاردانو فقط مثال ویدیو بودند.

## آیپد / همیشه روشن / بدون هزینه (پیشنهادی)

GitHub محل کار است: سه ایجنت مستقل در GitHub Actions به‌صورت حلقه‌ای اجرا می‌شوند و نتیجه روی GitHub Pages
منتشر می‌شود؛ آیپد فقط صفحه را باز می‌کند، هیچ کدی اجرا نمی‌کند، هیچ VPS لازم نیست.

| ایجنت | چرخه | کار |
|---|---|---|
| Phoenix 1 · Scan + Organization | ۱۰ دقیقه | ققنوس → ۹ دپارتمان → A34 → دروازهٔ ریسک → SIGNAL → قاضی نتیجه → تجربه؛ ناشر Pages؛ تلگرام سیگنال/نتیجه |
| Phoenix 2 · Intel | ۳۰ دقیقه | خبر، لیست/حذف بایننس، ترند، ترس‌وطمع، نبض X (Grok)؛ تلگرام خبر و رویداد مهم |
| Phoenix 3 · Watchdog | ۱۵ دقیقه | توقف غیرعادی → لاگ + مغز → اجرای مجدد / Issue / تلگرام؛ دستورات بات (`/status /signals /close`) |

- راهنما و Secrets: [`docs/IPAD_ZERO_COST.md`](docs/IPAD_ZERO_COST.md)
- سازمان ایجنت‌ها، منابع داده و حافظهٔ دائمی: [`docs/ORGANIZATION.md`](docs/ORGANIZATION.md)
- صفحه: `https://tradeosuli-hub.github.io/Crypto-agent-server/`
- Workflowها: `.github/workflows/phoenix-{pages,intel,watchdog}.yml` · حافظه: شاخهٔ `phoenix-memory` · UI: `site/`

## داشبورد لایو (کروم، روی سرور خودت)

```bash
pip install -r requirements.txt
python3 main.py live --port 8080
```

باز کردن: http://127.0.0.1:8080/

- پایش پیوسته با WebSocket
- SETUP فقط با ماشهٔ ۱۵دقیقه + امتیاز ≥۶ + R:R≥۱
- ستاپ نبود → WATCH + آلارم

## CLI

```bash
python3 main.py gates
python3 main.py scan --top 30 --json
python3 main.py scan --symbols BTCUSDT,ETHUSDT,SOLUSDT --json
```

## ساختار (فقط همین پنل)

```
phoenix/          موتور (ta, ghoghnoos, market_data, panel) + لایو اپ مستقل
phoenix/org/      سازمان: ۹ دپارتمان · اجماع · A34 · دروازهٔ ریسک · قاضی نتیجه · حافظه
phoenix/intel/    ایجنت اطلاعات: منابع تأییدشده (RSS، بایننس، CoinGecko، F&G) + نبض X با Grok
phoenix/watchdog.py  ایجنت عیب‌یابی/خودترمیم (GitHub API + لاگ + مغز + حافظهٔ رخدادها)
phoenix/notify.py    بات تلگرام (ارسال بدون تکرار + دستورات)
phoenix/brain.py     مغز اختیاری (Grok → OpenAI → قاعده‌محور)
phoenix/web/      داشبورد کروم (حالت سرور زنده / WebSocket)
site/             داشبورد استاتیک GitHub Pages با ۷ تب (حالت آیپد، بدون سرور)
scripts/          export_static.py · run_intel.py · run_watchdog.py · memory_sync.sh · watchdog_forever.py (سرور)
strategies/       اسپک و پرامپت متد حمید v3
docs/             پرامپت‌ها · IPAD_ZERO_COST · ORGANIZATION · ALWAYS_ON
main.py           CLI / live
```

## تست

```bash
pytest -q
```
