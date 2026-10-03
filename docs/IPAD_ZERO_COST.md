# ققنوس روی آیپد — همیشه روشن، بدون VPS، بدون هزینه

## معماری (چرا این کار می‌کند)
```
GitHub Actions (cron هر ۱۰ دقیقه، رایگان)
   └─ scripts/export_static.py  →  یک چرخهٔ کامل ققنوس روی ۳۰ ارز برتر
         ├─ site/data/latest.json    آخرین اسکن
         ├─ site/data/history.json   خلاصهٔ ۴۸ ساعت اخیر
         └─ site/data/signals.json   دفترچهٔ SETUPها (بدون تکرار)
   └─ deploy-pages  →  GitHub Pages (استاتیک، رایگان، همیشه در دسترس)
         └─ https://tradeosuli-hub.github.io/Crypto-agent-server/

آیپد (Safari/Chrome)  ←  فقط HTML/JSON می‌خواند؛ هیچ کدی روی آیپد اجرا نمی‌شود
تلگرام (اختیاری)      ←  هر SETUP تازه فوراً پیام می‌شود
```

- هیچ سروری نیست که بمیرد. اگر Cloud Agent خاموش شود، Actions همچنان هر ۱۰ دقیقه اجرا می‌شود.
- حافظهٔ بین اجراها (history / signals) از خودِ Pages خوانده و ادغام می‌شود.
- این پنل کاملاً مستقل است و به هیچ پنل دیگری دست نمی‌زند.

## راه‌اندازی (یک‌بار، از روی خودِ آیپد در مرورگر)
1. این شاخه را به `main` مرج کن (زمان‌بندی GitHub فقط روی شاخهٔ پیش‌فرض اجرا می‌شود).
2. در ریپو: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
   (Workflow با `enablement: true` تلاش می‌کند خودش این را فعال کند؛ اگر نشد، همین یک کلیک کافی است.)
3. **Actions → "Phoenix scan → GitHub Pages" → Run workflow** تا اولین اسکن منتشر شود.
4. روی آیپد باز کن: `https://tradeosuli-hub.github.io/Crypto-agent-server/`
   سپس **Share → Add to Home Screen** تا مثل اپ باز شود.

## اعلان تلگرام (اختیاری، رایگان)
- در BotFather یک بات بساز و توکن بگیر؛ `chat_id` خودت را از `@userinfobot` بگیر.
- **Settings → Secrets and variables → Actions → New repository secret**:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
- از آن پس هر SETUP تازه (ورود/استاپ/تارگت/R:R) به تلگرامت می‌آید.

## محدودیت‌های صادقانه
- زمان‌بندی GitHub حداقل ۵ دقیقه است و گاهی چند دقیقه تأخیر دارد؛ تصمیم ۱۵دقیقه‌ای متد با چرخهٔ ۱۰ دقیقه سازگار است، ولی ماشهٔ ۵دقیقه‌ای ممکن است با تأخیر دیده شود.
- وقتی Actions دیر اجرا شود، نشانِ وضعیت در صفحه زرد/قرمز می‌شود تا گمراه نشوی.
- اگر روزی خواستی تأخیر صفر داشته باشی، همین کد با `scripts/watchdog_forever.py` روی هر سرور همیشه‌روشنی هم اجرا می‌شود (docs/ALWAYS_ON.md).

## قوانین همچنان
- بدون SETUP روی ۱۵دقیقه → سیگنال نیست (WATCH + آلارم و برو ارز بعدی)
- حد نصاب ۶/۱۰ پایین نمی‌آید؛ پارامتر بی‌داده «کور» است نه «رد»
- استاپ چهارشرطی · R:R ≥ ۱ · اهرم از استاپ محاسبه می‌شود، نه برعکس
