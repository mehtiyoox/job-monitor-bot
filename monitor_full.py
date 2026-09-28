# -*- coding: utf-8 -*-
"""ربات کاریابی نسخه ۳ — تقویت‌شده

تغییرات نسبت به نسخه ۲:
  • پروفایل و هویت کامل ربات (نام، بیو، توضیحات)
  • پیکربندی آغاز خودکار با ویندوز (Task Scheduler)
  • امتیازدهی هوشمند: فقط پروژه‌های قابل تحویل
  • فیلتر سختگیرانه پروژه‌ای بودن (نه استخدام تمام‌وقت)
  • کش کردن Gemini: هر آگهی فقط یک‌بار تولید متن می‌شود
  • کنترل از تلگرام با دکمه‌های آماده
  • نرخ ملایم: هر ساعت یک‌بار، با جابجایی تصادفی منابع
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------
# سپر UTF-8: خروجی استاندارد را به UTF-8 تبدیل می‌کنیم تا ایموجی‌ها
# و متن فارسی روی ویندوز (cp1252) باعث کرش نشن.
def _force_utf8():
    import io
    try:
        if sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        # اگر موفق نشدیم، حداقل محیط را تنظیم می‌کنیم
        os.environ["PYTHONIOENCODING"] = "utf-8"

_force_utf8()

def safe_print(msg: str) -> None:
    """چاپ امن — هرگز کرش نمی‌کند."""
    try:
        print(msg, flush=True)
    except Exception:
        try:
            print(msg.encode("utf-8", "replace").decode("utf-8"), flush=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# مسیرها
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent
ENV_FILE = BASE / ".env"
DB_PATH = BASE / "jobs.db"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GROQ_KEY = os.environ.get("GROQ_KEY", "")
# رشته اتصال به PostgreSQL (روی سرور تنظیم می‌شود)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SOCKS_PORT = int(os.environ.get("SOCKS_PORT", "10808"))

# حداکثر تعداد تولید متن در هر اجرا — برای محافظت از سهمیه Gemini
MAX_PROPOSALS_PER_RUN = int(os.environ.get("MAX_PROPOSALS_PER_RUN", "3"))


# ---------------------------------------------------------------------------
# امتیازدهی: فقط پروژه‌هایی که واقعاً می‌توانیم انجام دهیم و تحویل دهیم
# ---------------------------------------------------------------------------
SKILLS = {
    # مهارت‌های اصلی ما (وزن بالا) — پروژه‌های قابل تحویل
    "ربات تلگرام": 12, "بات تلگرام": 12, "telegram bot": 12, "ربات تلیگرام": 12,
    "ربات": 9, "تلگرام": 7, "تلیگرام": 7,
    "اتوماسیون": 10, "automation": 10, "اتوماتیک": 8, "خودکار": 7,
    "ایجنت": 9, "agent": 8, "هوشمند": 5,
    "ورک‌فلو": 8, "workflow": 8, "n8n": 8, "make.com": 6, "zapier": 6,
    "چت‌بات": 10, "chatbot": 10, "چت بات": 10,
    "scraper": 8, "وب‌اسکریپر": 8, "خراش": 6, "اسکریپت": 6,
    "api": 5, "وب‌هوک": 5, "webhook": 5,
    "پایتون": 4, "python": 4, "برنامه‌نویسی": 3, "کدنویسی": 3,
    "هوش مصنوعی": 4, "ai": 3, "llm": 4,
    "اتصال": 3, "یکپارچه": 4, "یکپارچه‌سازی": 4, "integration": 4,
    "وردپرس": 3, "wordpress": 3, "وب‌سایت": 3, "سایت": 2,
}
# کلماتی که نشان می‌دهند پروژه به ما ربطی ندارد
IRRELEVANT = {
    # نامرتبط مطلق
    "ترجمه", "تایپ", "پایان‌نامه", "پایان نامه", "مقاله", "آنتن",
    "شبیه‌سازی", "فلوءنت", "fluent", "cst", "متلب", "matlab",
    "حسابداری", "فروش", "بازاریابی", "تولید محتوا", "نویسنده",
    "ادمین", "پشتیبانی", "منشی", "کارمند", "ویزیتور", "نماینده",
    "رزومه", "مصاحبه", "گرافیک", "طراحی لوگو", "عکاسی", "فیلم", "موشن",
    "روشنداری", "صنعتی", "برق صنعتی", "مواد", "شیمی", "نساجی",
    "کشاورزی", "حوزه", "وکیل", "حقوقی", "پزشکی", "پرستاری",
    "سالن", "رستوران", "کافه", "ویتر", "بخشش", "پیک",
    # 🔴 نشانگرهای استخدامی — ما پروژه‌ای کار می‌کنیم، نه استخدامی
    "استخدام", "تمام‌وقت", "تمام وقت", "پاره‌وقت", "پاره وقت",
    "کارآموز", "کار آموز", "حقوق", "مزایا", "بیمه تامین",
    "سنوات", "پاداش", "مرخصی", "اداره", "شرکت دهنده",
    "در محیط شرکت", "حضور در شرکت", "ساعت کاری",
    "تیم از راه دور", "همکار", "نیروی", "استخدامی",
    "minimum", "years experience", "سال سابقه",
}
# علائم یک پروژه واقعی (نه استخدام)
PROJECT_MARKERS = ["پروژه", "قیمت", "مبلغ", "بودجه", "پیشنهاد قیمت", "توافقی",
                   "project", "budget", "فریلنسر", "دورکاری پروژه‌ای",
                   "تحویل", "انجام پروژه", "outsourcing", "freelance"]
# 🔴 علائم استخدام — اگر این‌ها بود، پروژه نیست
EMPLOYMENT_MARKERS = [
    "استخدام", "کارمند", "کارآموز", "تمام‌وقت", "تمام وقت", "پاره‌وقت",
    "حقوق", "مزایا", "مرخصی", "سنوات", "بیمه تامین", "سابقه کار",
    "نیروی", "همکار", "تیم توسعه", "در محیط شرکت", "حضور در شرکت",
    "ساعت کاری", "اداره", "سال سابقه", "اشتغال",
]


# ---------------------------------------------------------------------------
# مدل
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Job:
    url: str
    title: str
    company: str
    location: str
    budget: str
    source: str
    score: int
    is_project: bool
    found_at: str


# ---------------------------------------------------------------------------
# شبکه
# ---------------------------------------------------------------------------
# پراکسی فقط روی سیستم محلی لازم است (تلگرام و Gemini در ایران فیلترند).
# روی سرور خارجی پراکسی لازم نیست — خودکار تشخیص می‌دهیم.
USE_PROXY = os.environ.get("USE_PROXY", "").lower() in ("1", "true", "yes")
if not USE_PROXY and os.environ.get("NO_PROXY_AUTO", "1") == "1":
    # اگر روی سیستم محلی هستیم و پراکسی Happ روشن است، استفاده کن
    # در غیر این صورت اتصال مستقیم (مخصوص سرور خارجی)
    USE_PROXY = bool(SOCKS_PORT and os.environ.get("LOCAL_RUN", "0") == "1")

if USE_PROXY:
    OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({
        "http": f"socks5h://127.0.0.1:{SOCKS_PORT}",
        "https": f"socks5h://127.0.0.1:{SOCKS_PORT}",
    }))
else:
    OPENER = urllib.request.build_opener()
NO_PROXY = urllib.request.build_opener()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
}


def fetch(url: str, timeout: int = 15, proxy: bool = False) -> Optional[str]:
    opener = OPENER if proxy else NO_PROXY
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(2):
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt == 1:
                safe_print(f"      ⚠️ fetch ناموفق: {url[:50]} ({type(e).__name__})")
                return None
            time.sleep(2)


# ---------------------------------------------------------------------------
# پایگاه داده (دو حالت: sqlite محلی / Postgres روی سرور)
# ---------------------------------------------------------------------------
if DATABASE_URL:
    try:
        import psycopg2
        from psycopg2 import sql as pg_sql  # noqa: F401
        HAS_POSTGRES = True
    except ImportError:
        HAS_POSTGRES = False
        safe_print("⚠️ DATABASE_URL تنظیم شده ولی psycopg2 نصب نیست")
else:
    HAS_POSTGRES = False


def init_db(dsn: str = ""):
    """ساخت/اتصال به دیتابیس. اگر dsn یا DATABASE_URL تنظیم شده باشد از
    PostgreSQL (سرور) استفاده می‌کند، در غیر این صورت از sqlite (محلی).
    یک آبجکت برمی‌گرداند که execute/fetchone/commit روی هر دو یکسان کار می‌کند."""
    url = dsn or DATABASE_URL
    if url and HAS_POSTGRES:
        conn = psycopg2.connect(url, connect_timeout=30)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS jobs (
            url TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT,
            budget TEXT, source TEXT, score INTEGER, is_project INTEGER,
            found_at TEXT, notified INTEGER DEFAULT 0, proposal TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY, value TEXT)""")
        return PgConn(conn)
    # حالت محلی: sqlite
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        url TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT,
        budget TEXT, source TEXT, score INTEGER, is_project INTEGER,
        found_at TEXT, notified INTEGER DEFAULT 0, proposal TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY, value TEXT)""")
    # مهاجرت: دیتابیس‌های قدیمی ستون‌های جدید ندارند
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "budget" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN budget TEXT DEFAULT ''")
    if "is_project" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN is_project INTEGER DEFAULT 0")
    conn.commit()
    return conn


class PgConn:
    """پوشش روی psycopg2 تا با sqlite3 سازگار باشد (cursor شفاف)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, v):
        pass


def is_new(conn, url: str) -> bool:
    return conn.execute("SELECT 1 FROM jobs WHERE url=%s", (url,)).fetchone() is None


def save_job(conn, job: Job, proposal: str = "") -> None:
    conn.execute("""INSERT INTO jobs
        (url,title,company,location,budget,source,score,is_project,
         found_at,notified,proposal)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (url) DO UPDATE SET
            title=EXCLUDED.title, company=EXCLUDED.company,
            location=EXCLUDED.location, budget=EXCLUDED.budget,
            source=EXCLUDED.source, score=EXCLUDED.score,
            is_project=EXCLUDED.is_project,
            found_at=EXCLUDED.found_at,
            proposal=CASE WHEN jobs.proposal='' THEN EXCLUDED.proposal
                          ELSE jobs.proposal END""",
        (job.url, job.title, job.company, job.location, job.budget,
         job.source, job.score, int(job.is_project),
         job.found_at or datetime.now().isoformat(timespec="seconds"),
         0, proposal))
    conn.commit()


# ---------------------------------------------------------------------------
# امتیازدهی
# ---------------------------------------------------------------------------
def score_and_classify(job: Job) -> Job:
    blob = f"{job.title} {job.company}".lower()
    positive = sum(w for kw, w in SKILLS.items() if kw in blob)
    negative = sum(3 for kw in IRRELEVANT if kw in blob)
    job.score = max(0, positive - negative)
    # 🔴 تشخیص پروژه بودن:
    # پارسکدرز ذاتاً پروژه‌ای است. جابینجا فقط اگر نشانه‌های پروژه داشته باشد
    # و نشانه‌های استخدامی نداشته باشد، پروژه محسوب می‌شود.
    has_project_marker = any(m in blob for m in PROJECT_MARKERS)
    has_employment_marker = any(w in blob for w in EMPLOYMENT_MARKERS)
    if job.source == "parscoders":
        job.is_project = not has_employment_marker
    else:
        job.is_project = has_project_marker and not has_employment_marker
    return job


# ---------------------------------------------------------------------------
# پارسر جابینجا
# ---------------------------------------------------------------------------
def parse_jobinja(html: str) -> list[Job]:
    jobs: list[Job] = []
    blocks = re.split(r'(?=<li[^>]*c-jobListView__item)', html)
    for b in blocks:
        if "c-jobListView__item" not in b[:400]:
            continue
        m_title = re.search(
            r'<a[^>]*c-jobListView__titleLink[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            b, re.S)
        if not m_title:
            continue
        url = urllib.parse.urljoin("https://jobinja.ir", m_title.group(1).split("?")[0])
        title = unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                          m_title.group(2)))).strip()
        if not title:
            continue

        meta = re.findall(r'<li[^>]*c-jobListView__metaItem[^>]*>(.*?)</li>', b, re.S)
        texts = [unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m))).strip()
                 for m in meta]
        texts = [t for t in texts if t]
        company = texts[0] if texts else ""
        location = texts[1] if len(texts) > 1 else ""

        jobs.append(Job(url=url, title=title, company=company, location=location,
                        budget="", source="jobinja", score=0, is_project=False,
                        found_at=datetime.now().isoformat(timespec="seconds")))
    seen, out = set(), []
    for j in jobs:
        if j.url in seen:
            continue
        seen.add(j.url)
        out.append(score_and_classify(j))
    return out


# ---------------------------------------------------------------------------
# پارسر پارسکدرز
# ---------------------------------------------------------------------------
def post_parscoders_search(keyword: str) -> list[Job]:
    """جستجوی کلمه‌کلیدی در پارسکدرز با API داخلی AJAX."""
    url = "https://www.parscoders.com/project/ajax/project-search"
    data = urllib.parse.urlencode({"keyword": keyword, "page": "1"}).encode()
    req = urllib.request.Request(url, data=data, headers={
        **HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.parscoders.com/project/only-available/1",
    })
    try:
        with NO_PROXY.open(req, timeout=20) as r:
            payload = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return []
    html_rows = payload.get("project-row", "")
    jobs: list[Job] = []
    for m in re.finditer(r'href="(/project/(\d+)/[^"]*)"[^>]*aria-label="([^"]+)"', html_rows):
        jurl = "https://www.parscoders.com" + unescape(m.group(1))
        title = re.sub(r"^عنوان پروژه\s*", "", unescape(m.group(3))).strip()
        if title:
            jobs.append(Job(url=jurl, title=title, company="کارفرما (پارسکدرز)",
                            location="", budget="", source="parscoders",
                            score=0, is_project=True,
                            found_at=datetime.now().isoformat(timespec="seconds")))
    seen, out = set(), []
    for j in jobs:
        if j.url in seen:
            continue
        seen.add(j.url)
        out.append(score_and_classify(j))
    return out


def parse_parscoders(html: str) -> list[Job]:
    jobs: list[Job] = []
    for m in re.finditer(r'href="(/project/(\d+)/[^"]*)"[^>]*aria-label="([^"]+)"', html):
        url = "https://www.parscoders.com" + unescape(m.group(1))
        # عنوان واقعی از aria-label (بدون «عنوان پروژه»)
        title = unescape(m.group(3)).strip()
        title = re.sub(r"^عنوان پروژه\s*", "", title)
        if not title:
            continue
        jobs.append(Job(url=url, title=title, company="کارفرما (پارسکدرز)",
                        location="", budget="", source="parscoders",
                        score=0, is_project=True,
                        found_at=datetime.now().isoformat(timespec="seconds")))
    seen, out = set(), []
    for j in jobs:
        if j.url in seen:
            continue
        seen.add(j.url)
        out.append(score_and_classify(j))
    return out


# ---------------------------------------------------------------------------
# فیلتر نهایی: آیا این کار برای ما مناسب است؟
# ---------------------------------------------------------------------------
def is_good_for_us(job: Job, min_score: int) -> bool:
    """شرط‌های سختگیرانه — فقط پروژه‌های قابل تحویل:
    ۱) حتماً پروژه باشد (نه موقعیت شغلی/استخدامی)
    ۲) امتیاز کافی
    ۳) از کارهای نامرتبط خبری نباشد
    ۴) عنوان استفاده‌نگر داشته باشد (پروژه‌ی واقعی)
    """
    # 🔴 قانون اول: فقط پروژه‌های فریلنسری. استخدامی‌ها اصلاً نمی‌خواهیم.
    if not job.is_project:
        return False
    if job.score < min_score:
        return False
    blob = f"{job.title} {job.company}".lower()
    # کارهای کاملاً نامرتبط را حذف کن
    hard_blocks = ["ترجمه", "تایپ", "پایان‌نامه", "مقاله", "متلب", "آنتن",
                   "شبیه‌سازی", "سالن", "رستوران", "حسابداری",
                   # کلمات استفاده‌نگر — پروژه نیستند
                   "استخدام", "تمام‌وقت", "تمام وقت", "پاره‌وقت",
                   "کارآموز", "حقوق", "مرخصی", "سنوات", "سابقه کار"]
    if any(b in blob for b in hard_blocks):
        return False
    return True


def is_deliverable_project(job: Job) -> bool:
    """بررسی نهایی: آیا این یک پروژه‌ی قابل تحویل است؟
    عنوان باید نشان‌دهنده‌ی یک کار مشخص باشد، نه یک موقعیت شغلی."""
    blob = f"{job.title} {job.company}".lower()
    # کلماتی که نشان می‌دهند این یک استخدام است نه پروژه
    employment_words = [
        "استخدام", "کارمند", "کارآموز", "تمام‌وقت", "تمام وقت",
        "پاره‌وقت", "حقوق", "مزایا", "مرخصی", "سنوات",
        "نیروی", "همکار", "تیم توسعه", "در محیط",
    ]
    return not any(w in blob for w in employment_words)


# ---------------------------------------------------------------------------
# تولید پیشنهاد با Gemini + کش
# ---------------------------------------------------------------------------
# تولید پیشنهاد با Groq (سریع و رایگان) + fallback به Gemini
# ---------------------------------------------------------------------------
# اول Groq، بعد Gemini
GROQ_MODELS = [
    "llama-3.3-70b-versatile",      # بهترین کیفیت
    "llama-3.1-8b-instant",         # سریع
    "qwen/qwen3-32b",
]
# Fallback به Gemini — ترتیب بر اساس دسترس‌پذیری روی سرورهای ابری
# (gemma روی GitHub Actions کار می‌کند، مدل‌های flash گاهی ۵۰۳ می‌دهند)
FALLBACK_MODELS = [
    "gemma-4-26b-a4b-it",
    GEMINI_MODEL,
    "gemini-flash-lite-latest",
]


def _call_groq(model: str, prompt: str):
    """فراخوانی Groq API (سازگار با OpenAI)"""
    url = "https://api.groq.com/openai/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 400,
        "temperature": 0.7,
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {GROQ_KEY}"})
    try:
        with OPENER.open(req, timeout=60) as r:
            d = json.loads(r.read().decode())
        txt = d["choices"][0]["message"]["content"].strip()
        return True, txt
    except urllib.error.HTTPError as e:
        return False, e.code
    except Exception as e:
        return False, str(e)[:60]


def _call_gemini(model: str, prompt: str):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={GEMINI_KEY}")
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=60) as r:
            d = json.loads(r.read().decode())
        return True, (d.get("candidates", [{}])[0]
                      .get("content", {}).get("parts", [{}])[0]
                      .get("text", "").strip())
    except urllib.error.HTTPError as e:
        return False, e.code
    except Exception as e:
        return False, str(e)[:60]


def generate_proposal(job: Job) -> str:
    prompt = f"""شما یک فریلنسر حرفه‌ی نرم‌افزار و متخصص اتوماسیون هستید.
برای این پروژه یک پیام پیشنهاد کوتاه، حرفه‌ی و جذاب فارسی بنویسید
(حداکثر ۴ جمله). مستقیم و مودبانه، بدون کلیشه. نشان دهید نیاز کارفرما
را خوانده‌اید و می‌توانید آن را تحویل دهید. فقط خود پیام را بنویسید،
بدون عنوان یا توضیح اضافه.

عنوان پروژه: {job.title}
شهر/کارفرما: {job.company or 'نامشخص'}

مهارت‌های ما: ساخت ربات تلگرام، اتوماسیون فرایندها، ایجنت هوشمند،
پایتون، وب‌اسکریپر، اتصال سرویس‌ها به هم."""

    # ۱) Groq (سریع‌ترین) — روی شبکه‌ی محلی کار می‌کند
    if GROQ_KEY:
        for i, model in enumerate(GROQ_MODELS):
            ok, result = _call_groq(model, prompt)
            if ok:
                return result
            if isinstance(result, int) and result in (429, 503, 529):
                safe_print(f"   ⏳ Groq/{model} شلوغ ({result}) — سراغ بعدی")
                time.sleep(min(5 * (i + 1), 10))
                continue

    # ۲) Fallback به Gemini — ترتیب: مدل‌های سبک‌تر اول
    # (روی سرورهای GitHub مدل‌های سنگین‌تر ۵۰۳ می‌دهند)
    if GEMINI_KEY:
        for i, model in enumerate(FALLBACK_MODELS):
            ok, result = _call_gemini(model, prompt)
            if ok:
                return result
            if isinstance(result, int) and result in (429, 503):
                safe_print(f"   ⏳ {model} شلوغ ({result}) — سراغ بعدی")
                time.sleep(min(3 * (i + 1), 8))
                continue

    return "⚠️ همه‌ی مدل‌ها شلوغ هستند — بعداً."


# ---------------------------------------------------------------------------
# تلگرام
# ---------------------------------------------------------------------------
def send_telegram(text: str) -> bool:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        safe_print("⚠️ TG_BOT_TOKEN یا TG_CHAT_ID تنظیم نیست.")
        return False
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": TG_CHAT_ID, "text": text,
                       "parse_mode": "Markdown",
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=30) as r:
            return r.status == 200
    except Exception as e:
        safe_print(f"⚠️ ارسال تلگرام ناموفق: {e}")
        return False


def notify(job: Job, proposal: str) -> None:
    badge = "🟢 پروژه فریلنسری" if job.is_project else "🔵 موقعیت شغلی"
    text = (
        f"{badge} (امتیاز {job.score})\n\n"
        f"*عنوان:* {job.title}\n"
        f"*کارفرما:* {job.company or '—'}\n"
        + (f"*شهر:* {job.location}\n" if job.location else "")
        + (f"*بودجه:* {job.budget}\n" if job.budget else "")
        + f"*منبع:* {job.source}\n"
        + f"*لینک:* {job.url}\n\n"
        f"📝 *متن پیشنهاد:*\n{proposal}"
    )
    send_telegram(text)


# ---------------------------------------------------------------------------
# کنترل از راه دور با تلگرام (دستورات + دکمه‌ها)
# ---------------------------------------------------------------------------
TG_OFFSET = 0  # شمارنده‌ی update برای long-polling


def load_tg_offset() -> int:
    """خواندن offset ذخیره‌شده (برای پایداری بین اجراها)"""
    try:
        conn = init_db()
        r = conn.execute("SELECT value FROM meta WHERE key=%s",
                         ("tg_offset",)).fetchone()
        conn.close()
        return int(r[0]) if r else 0
    except Exception:
        return 0


def save_tg_offset(offset: int) -> None:
    """ذخیره‌ی offset برای اجرای بعدی"""
    try:
        conn = init_db()
        conn.execute("""INSERT INTO meta (key, value) VALUES ('tg_offset', %s)
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""",
                     (str(offset),))
        conn.commit()
        conn.close()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# هویت و پروفایل ربات
# ---------------------------------------------------------------------------
BOT_PROFILE = {
    "name": "دستیار کاریابی | مهدی حبیب‌زاده",
    "about": "🤖 دستیار کاریابی هوشمند مهدی حبیب‌زاده — "
             "متخصص ربات تلگرام و اتوماسیون",
    "description": (
        "سلام! 👋 من دستیار کاریابی هوشمند مهدی حبیب‌زاده هستم.\n\n"
        "من هر ساعت سایت‌های کاریابی رو چک می‌کنم و پروژه‌های فریلنسری "
        "مرتبط با ربات تلگرام، اتوماسیون و ایجنت هوشمند رو پیدا می‌کنم "
        "و با متن پیشنهاد آماده برات می‌فرستم.\n\n"
        "🟢 شروع کن: /start\n"
        "📰 اسکن سریع: /new\n"
        "📋 لیست پروژه‌ها: /list\n"
        "📊 وضعیت: /status\n"
        "🚀 ارسال بهترین‌ها: /send"
    ),
}


def setup_bot_profile() -> None:
    """تنظیم نام، بیو و توضیحات ربات در تلگرام (یکی از اولین دفعات)"""
    if not TG_BOT_TOKEN:
        return
    token = TG_BOT_TOKEN
    api = f"https://api.telegram.org/bot{token}"
    commands = [
        {"command": "new", "description": "📰 اسکن آگهی‌های جدید"},
        {"command": "list", "description": "📋 لیست پروژه‌های ذخیره‌شده"},
        {"command": "send", "description": "🚀 ارسال بهترین پروژه‌ها"},
        {"command": "status", "description": "📊 وضعیت ربات"},
        {"command": "help", "description": "❓ راهنما"},
    ]
    # محدودیت‌های تلگرام: نام ≤۶۴، بیو ≤۱۲۰، توضیحات ≤۵۱۲
    api_calls = [
        ("setMyName", {"name": BOT_PROFILE["name"][:64]}),
        ("setMyShortDescription",
         {"short_description": BOT_PROFILE["about"][:120]}),
        ("setMyDescription",
         {"description": BOT_PROFILE["description"][:512]}),
        ("setMyCommands", {"commands": commands}),
    ]
    ok_count = 0
    for name, payload in api_calls:
        try:
            OPENER.open(urllib.request.Request(
                f"{api}/{name}",
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"}), timeout=20)
            ok_count += 1
        except Exception:
            safe_print(f"⚠️ {name} ناموفق")
    safe_print(f"✅ پروفایل ربات تنظیم شد ({ok_count}/{len(api_calls)})")


# کیبورد دکمه‌های آماده (همیشه پایین صفحه نمایش داده می‌شود)
COMMAND_KEYBOARD = {
    "keyboard": [
        [{"text": "📰 آگهی جدید"}, {"text": "📋 لیست پروژه‌ها"}],
        [{"text": "🚀 ارسال بهترین‌ها"}, {"text": "📊 وضعیت"}],
        [{"text": "❓ راهنما"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
    "is_persistent": True,
}


def tg_send(text: str, show_buttons: bool = False) -> None:
    """ارسال پیام به تلگرام + اختیاری: نمایش دکمه‌های آماده"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if show_buttons:
        payload["reply_markup"] = COMMAND_KEYBOARD
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        OPENER.open(req, timeout=30)
    except Exception:
        pass


def tg_answer(update: dict) -> None:
    """یک update تلگرام را پردازش می‌کند و جواب می‌دهد."""
    try:
        msg = update.get("message") or update.get("edited_message") or {}
        text = (msg.get("text") or "").strip()
        chat = msg.get("chat", {}).get("id")
        # لاگ برای دیباگ (همه‌ی پیام‌ها)
        _log_message(f"chat={chat} text={text[:40]!r}")
        safe_print(f"📨 پیام دریافت شد: chat={chat} text={text[:40]!r}")
        if chat is None or not text:
            return
        # فقط از صاحب حساب اجازه‌ی کنترل داریم
        if TG_CHAT_ID and str(chat) != str(TG_CHAT_ID):
            _log_message(f"رد شد: chat={chat}")
            safe_print(f"⚠️ chat={chat} مجاز نیست (مورد انتظار {TG_CHAT_ID})")
            return
        # 🎯 تطبیق روی کل متن دکمه (نه فقط کلمه‌ی اول) — دکمه‌ها چند کلمه‌ای هستند
        full = text.strip()
        cmd = full.lower().split()[0] if full.split() else ""

        def matches(*keys):
            return full in keys or cmd in keys

        if matches("/start", "/help", "help", "راهنما", "❓ راهنما"):
            tg_send(
                "🤖 *دستورات ربات کاریابی*\n\n"
                "📰 `/new` — آگهی‌های جدید (اسکن همین الان)\n"
                "📋 `/list` — همه‌ی پروژه‌های ذخیره‌شده\n"
                "🚀 `/send` — ساخت پروپوزال + ارسال بهترین‌ها\n"
                "📊 `/status` — وضعیت ربات\n"
                "❓ `/help` — همین راهنما\n\n"
                "_یا از دکمه‌های پایین صفحه استفاده کنید_",
                show_buttons=True)
        elif matches("/new", "new", "جدید", "آگهی", "📰 آگهی جدید"):
            tg_send("🔍 اسکن منابع شروع شد...", show_buttons=True)
            n = run_once(5, MAX_PROPOSALS_PER_RUN)
            if n == 0:
                tg_send("✅ پروژه‌ی جدیدی نبود.\n\n"
                        "📋 /list — پروژه‌های ذخیره‌شده", show_buttons=True)
        elif matches("/list", "list", "لیست", "📋 لیست پروژه‌ها"):
            conn = init_db()
            rows = conn.execute(
                "SELECT title, score, source, url FROM jobs WHERE is_project=1 "
                "ORDER BY score DESC LIMIT 10").fetchall()
            conn.close()
            if not rows:
                tg_send("📭 هیچ پروژه‌ای ذخیره نشده.", show_buttons=True)
            else:
                out = ["📋 *پروژه‌ها (۱۰ مورد برتر):*"]
                for i, r in enumerate(rows, 1):
                    out.append(f"{i}. ⭐{r[1]} | {r[0][:50]}\n   {r[3]}")
                tg_send("\n".join(out), show_buttons=True)
        elif matches("/send", "send", "بفرست", "🚀 ارسال بهترین‌ها"):
            n = backfill_proposals(3)
            if n == 0:
                tg_send("✅ پروژه‌ی معوقه‌ای نیست — همه ارسال شده‌اند.",
                        show_buttons=True)
            else:
                tg_send(f"✅ {n} پروژه ارسال شد.", show_buttons=True)
        elif matches("/status", "status", "وضعیت", "📊 وضعیت"):
            conn = init_db()
            total = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_project=1").fetchone()[0]
            unsent = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_project=1 AND "
                "(proposal='' OR proposal LIKE '⚠️%')").fetchone()[0]
            conn.close()
            tg_send(
                "📊 *وضعیت ربات*\n\n"
                f"🟢 فعال و در حال اجرا\n"
                f"📦 پروژه‌های ذخیره‌شده: {total}\n"
                f"📨 پروژه‌های ارسال‌نشده: {unsent}\n\n"
                f"📰 /new — اسکن جدید\n"
                f"📋 /list — لیست پروژه‌ها",
                show_buttons=True)
        else:
            tg_send(
                "❓ دستور شناخته نشد.\n\n"
                "📰 /new — آگهی‌های جدید\n"
                "📋 /list — لیست پروژه‌ها\n"
                "🚀 /send — ارسال بهترین‌ها\n"
                "📊 /status — وضعیت",
                show_buttons=True)
    except Exception as e:
        safe_print(f"⚠️ خطای پردازش دستور: {e}")
    finally:
        LOOP_STATE["commands_handled"] += 1


def _log_message(text: str) -> None:
    """پیام‌های اخیر را برای دیباگ نگه می‌دارد."""
    lst = LOOP_STATE["recent_messages"]
    lst.append(f"{datetime.now().strftime('%H:%M:%S')} {text}")
    if len(lst) > 20:
        del lst[0]


def poll_telegram_commands(idle_wait: int) -> None:
    """دستورات تلگرام را به‌صورت long-polling می‌خواند.
    این تابع هرگز کرش نمی‌کند — در حلقه‌ی اصلی صدا زده می‌شود."""
    global TG_OFFSET
    try:
        # offset ذخیره‌شده را بارگذاری کن (برای اجراهای کوتاه مثل GitHub Actions)
        if TG_OFFSET == 0:
            TG_OFFSET = load_tg_offset()
        url = (f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates"
               f"?timeout={idle_wait}&offset={TG_OFFSET}")
        req = urllib.request.Request(url, headers=HEADERS)
        with OPENER.open(req, timeout=idle_wait + 15) as r:
            payload = json.loads(r.read().decode())
        for upd in payload.get("result", []):
            TG_OFFSET = upd.get("update_id", 0) + 1
            tg_answer(upd)
        # offset را برای اجرای بعدی ذخیره کن
        if TG_OFFSET > 0:
            save_tg_offset(TG_OFFSET)
    except Exception:
        pass  # خطای موقت — در دور بعدی دوباره تلاش می‌کند


# ---------------------------------------------------------------------------
# منابع جستجو
# ---------------------------------------------------------------------------
SOURCES = [
    # (نام، URL یا کلمه‌کلیدی پارسکدرز)
    # پارسکدرز = پروژه‌های فریلنسری واقعی (قابل تحویل) ✅
    ("parscoders_latest", "https://www.parscoders.com/project/only-available/1"),
    ("parscoders_bot", "ربات تلگرام"),
    ("parscoders_automation", "اتوماسیون"),
    ("parscoders_python", "پایتون"),
    ("parscoders_n8n", "n8n"),
    ("parscoders_chatbot", "چت بات"),
    ("parscoders_scraper", "اسکریپت"),
    # جابینجا = بیشتر استخدامی است؛ فقط فیلتر پروژه‌ای فعال می‌کنیم
    # (is_good_for_us استخدامی‌ها را حذف می‌کند)
    ("jobinja_bot", "https://jobinja.ir/jobs?filters%5Bkeywords%5D%5B0%5D="
                    + urllib.parse.quote("ربات") + "&sort_by=published_at_desc"),
]


def run_once(min_score: int = 5, max_proposals: int = MAX_PROPOSALS_PER_RUN) -> int:
    """یک دور کامل جستجو. فقط max_proposals متن پیشنهاد تولید می‌کند
    تا سهمیه‌ی Gemini تمام نشود."""
    safe_print("🔌 اتصال به دیتابیس...")
    conn = init_db()
    safe_print("✅ دیتابیس آماده")
    # جابجایی تصادفی ترتیب منابع
    sources = SOURCES[:]
    random.shuffle(sources)

    candidates: list[Job] = []
    for name, target in sources:
        safe_print(f"⏳ [{name}] — شروع")
        t0 = time.time()
        jobs: list[Job] = []
        try:
            if target.startswith("http"):
                html = fetch(target, proxy=False)
                if not html:
                    safe_print("   ❌ ناموفق")
                    continue
                if "parscoders" in target:
                    jobs = parse_parscoders(html)
                else:
                    jobs = parse_jobinja(html)
            else:
                # کلمه‌کلیدی پارسکدرز
                jobs = post_parscoders_search(target)
        except Exception as e:
            safe_print(f"   ❌ خطا در [{name}]: {type(e).__name__} — رد می‌شود")
            continue
        new = [j for j in jobs if is_new(conn, j.url) and is_good_for_us(j, min_score)]
        safe_print(f"   📄 {len(jobs)} آگهی، {len(new)} مورد مناسب "
                   f"({time.time()-t0:.1f}s)")
        candidates.extend(new)
        time.sleep(random.uniform(1.5, 3))

    if not candidates:
        safe_print("✅ پروژه‌ی جدیدی نبود")
        conn.close()
        return 0

    # بهترین‌ها را انتخاب کن — حذف تکرار درون اجرایی
    seen_urls: set[str] = set()
    unique: list[Job] = []
    for j in candidates:
        if j.url in seen_urls:
            continue
        seen_urls.add(j.url)
        unique.append(j)
    # مرتب‌سازی: اول پروژه‌های قابل تحویل با امتیاز بالا
    unique.sort(key=lambda j: (j.is_project and is_deliverable_project(j), j.score),
                reverse=True)
    candidates = unique[:max_proposals]

    sent = 0
    for j in candidates:
        safe_print(f"⭐ {j.title[:50]} (امتیاز {j.score}, "
                   f"{'پروژه' if j.is_project else 'موقعیت'})")
        # قبل از هر چیز ذخیره کن تا در همین اجرا تکرار نشود
        save_job(conn, j, "")
        proposal = generate_proposal(j)
        if proposal.startswith("⚠️"):
            # Gemini تمام شده — متن را بعداً تکمیل می‌کنیم
            conn.execute("UPDATE jobs SET proposal=%s WHERE url=%s", (proposal, j.url))
            conn.commit()
            safe_print("   💾 ذخیره شد، بعداً تکمیل می‌شود")
            continue
        conn.execute("UPDATE jobs SET proposal=%s WHERE url=%s", (proposal, j.url))
        conn.commit()
        notify(j, proposal)
        sent += 1
        time.sleep(random.uniform(2, 4))

    conn.close()
    return sent


def backfill_proposals(limit: int = 10) -> int:
    """تکمیل پیشنهادهای معوقه"""
    conn = init_db()
    rows = conn.execute(
        "SELECT url,title,company,location,budget,source,score,is_project,found_at "
        "FROM jobs WHERE proposal = '' OR proposal LIKE '⚠️%' "
        "ORDER BY is_project DESC, score DESC LIMIT %s", (limit,)).fetchall()
    if not rows:
        safe_print("✅ پیشنهاد معوقه‌ای نیست")
        conn.close()
        return 0
    safe_print(f"🔁 تکمیل {len(rows)} پیشنهاد معوقه")
    filled = 0
    for r in rows:
        job = Job(url=r[0], title=r[1], company=r[2], location=r[3], budget=r[4],
                  source=r[5], score=r[6], is_project=bool(r[7]), found_at=r[8])
        proposal = generate_proposal(job)
        if proposal.startswith("⚠️"):
            safe_print(f"   ⏳ هنوز: {job.title[:35]}")
            continue
        conn.execute("UPDATE jobs SET proposal=%s WHERE url=%s", (proposal, job.url))
        conn.commit()
        notify(job, proposal)
        filled += 1
        safe_print(f"   ✅ {job.title[:35]}")
        time.sleep(random.uniform(3, 5))
    conn.close()
    return filled


# ---------------------------------------------------------------------------
# سرور keep-alive — برای اینکه HF Space بخوابد نرود
# ---------------------------------------------------------------------------
KEEPALIVE_PORT = int(os.environ.get("PORT", "7860"))


# ---------------------------------------------------------------------------
# متغیرهای عمومی برای مانیتورینگ حلقه‌ی اصلی
LOOP_STATE = {
    "started_at": "",
    "last_poll": "",
    "polls": 0,
    "last_scan": "",
    "scans": 0,
    "commands_handled": 0,
    "recent_messages": [],  # ۲۰ پیام اخیر برای دیباگ
}


def _keepalive_worker() -> None:
    """سرور HTTP کوچک در یک thread جدا — پورت HF Space را پاسخ می‌دهد."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/state":
                body = json.dumps(LOOP_STATE, ensure_ascii=False,
                                  indent=1).encode()
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            try:
                conn = init_db()
                total = conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE is_project=1").fetchone()[0]
                conn.close()
            except Exception:
                total = -1
            body = (f"🟢 Job Monitor alive — projects: {total} — "
                    f"{datetime.now().isoformat(timespec='seconds')}").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass  # لاگ نگیر

    try:
        srv = HTTPServer(("0.0.0.0", KEEPALIVE_PORT), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        safe_print(f"🌐 keep-alive سرور روی پورت {KEEPALIVE_PORT}")
    except Exception as e:
        safe_print(f"⚠️ keep-alive سرور روشن نشد: {e}")


def _self_ping() -> None:
    """پینگ خودکار هر ۵ دقیقه برای جلوگیری از خوابیدن سرویس ابری."""
    import threading
    import socket
    # شناسه‌ی سرویس از متغیرهای محیطی — روی Render و HF کار می‌کند
    host = (os.environ.get("RENDER_EXTERNAL_URL")
            or os.environ.get("SPACE_HOST")
            or "").replace("https://", "").replace("http://", "")
    if not host:
        return  # فقط روی سرویس ابری فعال است

    def ping():
        while True:
            try:
                time.sleep(280)  # ~۵ دقیقه
                url = f"https://{host}/"
                req = urllib.request.Request(url, headers=HEADERS)
                urllib.request.urlopen(req, timeout=30)
            except Exception:
                # fallback: پورت محلی
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(5)
                    s.connect(("127.0.0.1", KEEPALIVE_PORT))
                    s.close()
                except Exception:
                    pass

    threading.Thread(target=ping, daemon=True).start()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--loop", action="store_true", help="اجرای مداوم")
    p.add_argument("--interval", type=int, default=3600, help="فاصله (ثانیه)")
    p.add_argument("--min-score", type=int, default=5)
    p.add_argument("--max-proposals", type=int, default=MAX_PROPOSALS_PER_RUN)
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--no-keepalive", action="store_true",
                   help="غیرفعال کردن سرور keep-alive (سیستم محلی)")
    a = p.parse_args()

    if a.backfill:
        n = backfill_proposals(a.max_proposals)
        safe_print(f"✅ {n} پیشنهاد معوقه تکمیل شد")
        return

    # هنگام شروع، پروفایل ربات را تنظیم کن
    setup_bot_profile()

    # 🎯 حالت تک‌بار (GitHub Actions): اسکن کن و تمام شو
    # بدون --loop، فقط یک بار اجرا می‌شود
    if not a.loop:
        n = run_once(a.min_score, a.max_proposals)
        safe_print(f"✅ {n} پروژه ارسال شد")
        return

    # سرور keep-alive (فقط روی سرور فعال — روی سیستم محلی بی‌خطر است)
    if not a.no_keepalive:
        _keepalive_worker()
        _self_ping()

    # حلقه‌ی مقاوم در برابر خطا — هرگز به‌طور کامل از کار نمی‌افتد
    # این حلقه هم اسکن دوره‌ای انجام می‌دهد و هم به دستورات تلگرام
    # پاسخ می‌دهد (long-polling).
    LOOP_STATE["started_at"] = datetime.now().isoformat(timespec="seconds")
    last_scan = time.time()
    while True:
        # --- گوش دادن به دستورات تلگرام (۱۵ ثانیه) ---
        poll_telegram_commands(15)
        LOOP_STATE["polls"] += 1
        LOOP_STATE["last_poll"] = datetime.now().isoformat(timespec="seconds")
        # --- زمان اسکن دوره‌ای رسیده است؟ ---
        if time.time() - last_scan >= max(60, a.interval):
            safe_print(f"\n=== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                       f"=== (اسکن دوره‌ای) ===")
            try:
                n = run_once(a.min_score, a.max_proposals)
                safe_print(f"✅ {n} پروژه ارسال شد")
            except Exception as e:
                safe_print(f"❌ خطا (ادامه می‌دهیم): {e}")
            LOOP_STATE["scans"] += 1
            LOOP_STATE["last_scan"] = datetime.now().isoformat(
                timespec="seconds")
            last_scan = time.time()


if __name__ == "__main__":
    main()
