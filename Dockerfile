FROM python:3.11-slim

# نصب کتابخانه‌های سیستم مورد نیاز psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# نصب وابستگی‌های پایتون
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی کد
COPY . .

# تنظیم متغیرهای محیطی پیش‌فرض
ENV PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    USE_PROXY=0 \
    LOCAL_RUN=0

# پورت برای keep-alive server
EXPOSE 7860

# اجرای ربات
CMD ["python", "-u", "monitor_full.py", "--loop", "--interval", "3600", \
     "--min-score", "5", "--max-proposals", "3"]
