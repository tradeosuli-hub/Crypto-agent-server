# پایش دائمی ققنوس (Never-Stop)

## چرا لینک آیپد قطع شد؟
Cloud Agent موقتی است. با خاموش‌شدن محیط، `uvicorn` و تونل `trycloudflare` می‌میرند.
لینک موقت برای دمو بود، نه هاست دائمی.

## راه‌حل پیش‌فرض (رایگان، بدون سرور، مناسب آیپد)
**GitHub Actions + GitHub Pages** — ببین: `docs/IPAD_ZERO_COST.md`.
هیچ کدی روی آیپد اجرا نمی‌شود و هیچ VPS لازم نیست.

## راه‌حل جایگزین: هاست همیشه روشن + نگهبان خودترمیم (اگر سرور داشتی)

روی یک VPS / سرور خانگی / Render / Railway:

```bash
cd /path/to/this/panel
pip install -r requirements.txt

# پایش دائمی — اگر پنل بمیرد دوباره بالا می‌آید و اسکن را از سر می‌گیرد
PHOENIX_TOP=30 PHOENIX_INTERVAL=90 python3 scripts/watchdog_forever.py
```

با systemd (پیشنهادی):

```ini
# /etc/systemd/system/phoenix-watchdog.service
[Unit]
Description=Phoenix Hamid forever watchdog
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/phoenix-panel
Environment=PHOENIX_PORT=8080
Environment=PHOENIX_TOP=30
Environment=PHOENIX_INTERVAL=90
ExecStart=/usr/bin/python3 scripts/watchdog_forever.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now phoenix-watchdog
```

آدرس پایدار برای آیپد: دامنهٔ خودت یا Cloudflare **Named Tunnel** (نه Quick Tunnel موقت).

## قوانین همچنان
- بدون SETUP روی ۱۵دقیقه → سیگنال نیست
- حد نصاب ۶ پایین نمی‌آید
- استاپ چهارشرطی · R:R ≥ ۱
