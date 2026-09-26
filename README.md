# پنل سیگنال‌دهی ققنوس — متد حمید نسخهٔ ۳

قوانین برای **همهٔ ارزها یکسان** است. سولانا/کاردانو فقط مثال ویدیو بودند.

## چیست؟

پنل `Phoenix` قبل از هر نگهبان، استراتژی **ققنوس** را با متد حمید v3 اجرا می‌کند:

- آبشار: دامیننس → 4h → 1h → 15m → 5m
- مرجع: 1h · تصمیم و ارسال: **فقط 15m**
- اوردر بلاک دائمی + قانون دیوار/چکش
- بازگشت بی‌قید به کانال
- ده پارامتر · حد نصاب ۶
- استاپ چهارشرطی · حداقل R:R = ۱
- بدون SETUP ققنوس → هیچ SIGNALی صادر نمی‌شود (فقط WATCH + آلارم)

## نصب

```bash
pip install -r requirements.txt
```

## استفاده

```bash
# گیت‌های سخت متد
python main.py gates

# اسکن ۳۰ ارز برتر (حجم فیوچرز بایننس) — قوانین یکسان
python main.py scan --top 30 --json

# ارزهای مشخص
python main.py scan --symbols BTCUSDT,ETHUSDT,SOLUSDT --json

# API
python main.py serve --port 8080
# POST /scan?top=20
# GET  /evaluate/SOLUSDT
```

## ساختار

```
docs/HAMID_METHOD_V3_PROMPT.txt   پرامپت کامل متد
docs/GHOGHNOOS_PROMPT.txt         پرامپت استراتژی ققنوس
strategies/hamid_method_spec.json اسپک ماشین‌خوان
strategies/hamid_method.py        بارگذاری اسپک/پرامپت/گیت‌ها
phoenix/ta.py                     موتور تکنیکال
phoenix/ghoghnoos.py              استراتژی ققنوس
phoenix/panel.py                  چرخهٔ اسکن همهٔ ارزها
phoenix/council.py                شورا / تأیید
phoenix/market_data.py            دادهٔ بایننس
main.py                           CLI + API
tests/                            تست واحد
```

## نکات صادقانه

- نقشهٔ لیکوییدیشن واقعی CoinGlass هنوز نیست → فالبک از قیمت+حجم.
- دامیننس USDT.D واقعی نیست → پروکسی از BTC (اگر کور باشد وتو نمی‌کند).
- خبر و DXY زنده فعلاً «کور»اند (در چک‌لیست رد نمی‌شوند).
- چند پارامتر عددی (lookback کانال، وزن تایم‌فریم‌ها، ATRها) در اسپک زیر `guessed_not_confirmed_by_hamid` علامت خورده‌اند تا با قانون حمید قاطی نشوند.

## تست

```bash
pytest -q
```
