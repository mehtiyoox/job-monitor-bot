---
title: Job Monitor Bot
emoji: 🤖
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
app_port: 7860
---

# 🤖 ربات کاریابی هوشمند — مهدی حبیب‌زاده

ربات کاریابی که هر ساعت پروژه‌های فریلنسری مرتبط را پیدا می‌کند
و با متن پیشنهاد آماده برای کارفرما ارسال می‌کند.

## 🔧 متغیرهای محیطی (در HF Space → Settings → Repository secrets)

| متغیر | توضیح |
|---|---|
| `TG_BOT_TOKEN` | توکن ربات تلگرام |
| `TG_CHAT_ID` | آیدی چت دریافت‌کننده |
| `GROQ_KEY` | کلید Groq API |
| `GEMINI_KEY` | کلید Gemini (fallback) |
| `DATABASE_URL` | رشته‌ی اتصال PostgreSQL (Neon) |

## 🚀 اجرای محلی

```bash
python monitor_full.py --loop --interval 3600
```
