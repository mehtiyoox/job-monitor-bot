# -*- coding: utf-8 -*-
"""دستورات سریع برای دیدن و ارسال آگهی‌های جدید

روش استفاده:
  python jobs.py              ← نمایش آگهی‌های جدیدِ مناسب
  python jobs.py all          ← نمایش همه‌ی پروژه‌های ذخیره‌شده
  python jobs.py send         ← ساخت پروپوزال + ارسال بهترین‌ها به تلگرام
  python jobs.py send 5       ← ارسال ۵ مورد
"""
from __future__ import annotations

import io
import os
import sys

# سپر UTF-8 (برای ویندوز)
try:
    if sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# وارد کردن ربات اصلی
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "mf", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "monitor_full.py"))
_mf = importlib.util.module_from_spec(_spec)
sys.modules["mf"] = _mf
_spec.loader.exec_module(_mf)


def color(v, n):
    """رنگ‌بندی امتیاز"""
    if v >= 25:
        return f"🌟 {v}"
    if v >= 12:
        return f"⭐ {v}"
    return f"▪️ {v}"


def cmd_list(new_only: bool) -> None:
    """نمایش پروژه‌ها"""
    conn = _mf.init_db()
    if new_only:
        # پروژه‌هایی که هنوز پروپوزال ندارن یا Gemini شلوغ بوده
        rows = conn.execute(
            "SELECT title, score, source, url, proposal, is_project "
            "FROM jobs WHERE (proposal='' OR proposal LIKE '⚠️%') "
            "AND is_project=1 ORDER BY score DESC").fetchall()
        print("\n🆕 پروژه‌های جدیدِ مناسب (هنوز ارسال نشده):")
    else:
        rows = conn.execute(
            "SELECT title, score, source, url, proposal, is_project "
            "FROM jobs WHERE is_project=1 ORDER BY score DESC").fetchall()
        print("\n📋 همه‌ی پروژه‌های ذخیره‌شده:")

    if not rows:
        print("   (چیزی یافت نشد)")
        conn.close()
        return

    print("=" * 62)
    for i, r in enumerate(rows, 1):
        title, score, source, url, proposal = r[0], r[1], r[2], r[3], r[4]
        sent = "" if (proposal == "" or proposal.startswith("⚠️")) else "  ✅ارسال‌شده"
        print(f"\n{i}. {color(score, 0)} | {source}{sent}")
        print(f"   {title[:70]}")
        print(f"   {url[:80]}")
    print("\n" + "=" * 62)
    print(f"مجموع: {len(rows)} پروژه")
    if new_only:
        print("💡 برای ارسال: python jobs.py send")
    conn.close()


def cmd_send(count: int) -> None:
    """ساخت پروپوزال و ارسال بهترین پروژه‌ها"""
    conn = _mf.init_db()
    rows = conn.execute(
        "SELECT url,title,company,location,budget,source,score,is_project,found_at "
        "FROM jobs WHERE (proposal='' OR proposal LIKE '⚠️%') AND is_project=1 "
        "ORDER BY score DESC LIMIT ?", (count,)).fetchall()
    if not rows:
        print("✅ پروژه‌ی جدیدی برای ارسال نیست")
        conn.close()
        return

    print(f"\n🚀 شروع ارسال {len(rows)} پروژه...")
    sent = 0
    for r in rows:
        job = _mf.Job(url=r[0], title=r[1], company=r[2], location=r[3],
                      budget=r[4], source=r[5], score=r[6],
                      is_project=bool(r[7]), found_at=r[8])
        print(f"\n⭐ {job.title[:60]} (امتیاز {job.score})")
        proposal = _mf.generate_proposal(job)
        if proposal.startswith("⚠️"):
            print("   ⏳ Gemini شلوغ است — بعداً دوباره امتحان کنید")
            conn.execute("UPDATE jobs SET proposal=? WHERE url=?",
                         (proposal, job.url))
            conn.commit()
            continue
        conn.execute("UPDATE jobs SET proposal=? WHERE url=?",
                     (proposal, job.url))
        conn.commit()
        if _mf.notify(job, proposal):
            sent += 1
            print("   ✅ ارسال شد به تلگرام")
        else:
            print("   ❌ ارسال تلگرام ناموفق")
        import time
        time.sleep(2)
    conn.close()
    print(f"\n✅ {sent} پروژه ارسال شد")


def main() -> None:
    a = sys.argv[1] if len(sys.argv) > 1 else ""
    if a == "all":
        cmd_list(new_only=False)
    elif a == "send":
        n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 3
        cmd_send(n)
    elif a in ("-h", "--help", "help"):
        print(__doc__)
    else:
        cmd_list(new_only=True)


if __name__ == "__main__":
    main()
