# پنل مستقل ققنوس — متد حمید نسخهٔ ۳

> **جداسازی:** این پنل کاملاً مستقل است و هیچ پنل سیگنال دیگری در گیت‌هاب را تغییر نمی‌دهد.
> جزئیات: [`STANDALONE.md`](STANDALONE.md)

قوانین برای **همهٔ ارزها یکسان** است. سولانا/کاردانو فقط مثال ویدیو بودند.

## داشبورد لایو (کروم)

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
phoenix/          موتور + لایو اپ مستقل
phoenix/web/      داشبورد کروم
strategies/       اسپک و پرامپت متد حمید v3
docs/             پرامپت‌ها
main.py           CLI / live
```

## تست

```bash
pytest -q
```
