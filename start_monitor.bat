@echo off
chcp 65001 >nul
title Job Monitor - Karyabi v3
cd /d "E:\DeepSiik"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
set PYTHONLEGACYWINDOWSSTDIO=0
:: روی سیستم محلی از پراکسی Happ استفاده کن
set LOCAL_RUN=1
:: هر ۳۶۰۰ ثانیه (یک ساعت)، حداکثر ۳ پیشنهاد در هر اجرا
:: برای محافظت از سهمیه رایگان Gemini
:: حلقه داخلی کد به هر خطا مقاوم است — حتی اگر یک دور شکست بخورد، دور بعدی ادامه می‌یابد
python monitor_full.py --loop --interval 3600 --min-score 5 --max-proposals 3 --no-keepalive >> "E:\DeepSiik\monitor_loop.log" 2>&1
