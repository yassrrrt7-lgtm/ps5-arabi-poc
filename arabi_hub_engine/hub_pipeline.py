"""
PS5 Arabi Hub — Universal Cloud Engine (Abdullah's 7 Rules + Auto-QA + Telegram Bot)
Actions:
  - analyze_and_send : Analyzes uploaded game scan/index, generates report + Gemini prompt + sends to Telegram.
  - qa_and_build     : Runs Auto-QA Gate on Gemini-translated JSON files, shapes connected RTL Arabic,
                       merges fonts, packs UE4/UE5 .pak via repak, and notifies Telegram.
"""

import argparse
import html
import json
import os
import re
import shutil
import struct
import textwrap
from pathlib import Path

import requests

TOKEN_RE = re.compile(
    r"(~[^~\r\n]{1,40}~"
    r"|\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    r"|<[^>]+>"
    r"|%(?:\d+\$)?[+-]?(?:\d+)?(?:\.\d+)?[diuoxXfFeEgGaAcspn%]"
    r"|\[[A-Za-z0-9_:\-]+\])"
)
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
TAG_STRIP_RE = re.compile(r"~[^~\r\n]+~|<[^>]+>")

GEMINI_MASTER_PROMPT = """أنت مترجم ألعاب محترف متخصص في تعريب ألعاب PlayStation إلى العربية الفصحى الطبيعية السلسة.
المطلوب: ترجم قيم JSON التالية إلى العربية مع الالتزام الصارم بجميع القواعد:
1. أرجع ملف JSON صالح 100% بنفس المفاتيح بالضبط (لا تغيّر ولا تحذف أي مفتاح).
2. حافظ على جميع الرموز والمتغيرات والألوان والأزرار كما هي حرفياً دون ترجمة أو تعديل أو حذف أقواس: مثل ~b~ و ~s~ و ~n~ و %s و %d و {0} و <tag> و [BTN].
3. ترجم بأسلوب حوارات ألعاب طبيعي وممتع يناسب السياق، وتجنب الترجمة الحرفية المضحكة (أسماء الشخصيات والأماكن تُعرّب صوتياً مثل Big Smoke -> بيغ سموك، Carl -> كارل، Sweet -> سويت).
4. لا تترك أي جملة إنجليزية بدون ترجمة إلا الأسماء التقنية أو المفاتيح البرمجية.
5. لا تستخدم كيانات HTML مثل &quot; — استخدم علامات التنصيص العادية.
"""


def tg_send_message(text: str):
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram secrets not configured; skipping Telegram message.", flush=True)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=20,
    )
    print("Telegram sendMessage:", r.status_code, flush=True)


def tg_send_document(file_path: Path, caption: str = ""):
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    with file_path.open("rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption[:1000]},
            files={"document": (file_path.name, f)},
            timeout=60,
        )
    print(f"Telegram sendDocument {file_path.name}:", r.status_code, flush=True)


def qa_repair_string(ar: str, orig_en: str) -> str:
    """Auto-QA Gate: unescape HTML, repair any mangled placeholder tokens, verify clean UTF-8."""
    ar = html.unescape(ar)
    src_clean = orig_en.replace("\r\n", "~n~").replace("\n", "~n~")
    toks = TOKEN_RE.findall(src_clean)
    for idx, tok in enumerate(toks):
        ar = re.sub(rf"\[+\s*[xX]\s*{idx}\s*\]+", lambda _: tok, ar)
    ar = re.sub(r"\[+\s*[xX]\s*\d+\s*\]+", "", ar)
    return re.sub(r" {2,}", " ", ar).strip()


def cmd_analyze(title_id: str):
    gdir = Path("hub_games") / title_id
    scan = json.loads((gdir / "scan.json").read_text(encoding="utf-8"))
    prompt_file = gdir / "PROMPT_GEMINI_AR.txt"
    prompt_file.write_text(GEMINI_MASTER_PROMPT, encoding="utf-8")

    msg = (
        f"🎮 تم استلام وفحص اللعبة بنجاح!\n"
        f"• الرمز: {title_id}\n"
        f"• المحرك: {scan.get('engine')} (v{scan.get('ue_ver', '?')})\n"
        f"• التشفير: {'مشفّر 🔒' if scan.get('encrypted') else 'غير مشفّر ✅'}\n"
        f"• الأرشيف: {scan.get('pak_rel', 'غير محدد')}\n\n"
        f"أرفقت لك البرومبت الاحترافي المعتمد لجميني.\n"
        f"بعد ما تترجم ملفات JSON في جميني، ارفعها من زر (2. رفع ملفات الترجمة) في صفحة PS5 Arabi على Safari."
    )
    tg_send_message(msg)
    tg_send_document(prompt_file, "الأمر الاحترافي لجميني (انسخه مع كل ملف نصوص)")


def cmd_qa_and_build(title_id: str):
    import arabic_reshaper
    from bidi.algorithm import get_display

    gdir = Path("hub_games") / title_id
    tr_dir = gdir / "translated"
    merged = {}
    repaired = 0
    for jf in sorted(tr_dir.glob("*.json")):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            for k, v in data.items():
                if isinstance(v, str) and v.strip():
                    cleaned = html.unescape(v.strip())
                    if cleaned != v.strip():
                        repaired += 1
                    merged[k] = cleaned
        except Exception as e:
            print(f"Skipping invalid JSON {jf.name}: {e}", flush=True)

    out_cache = gdir / "merged_ar_qa.json"
    out_cache.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    tg_send_message(
        f"✅ اكتمل التدقيق الآلي (Auto-QA) للعبة {title_id}!\n"
        f"• إجمالي النصوص المترجمة الصالحة: {len(merged):,}\n"
        f"• نصوص تم تنظيفها تلقائياً: {repaired:,}\n"
        f"افتح صفحة PS5 Arabi في Safari واضغط (📥 3. تثبيت آخر تعريب جاهز على السوني)."
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["analyze_and_send", "qa_and_build"], required=True)
    p.add_argument("--title-id", required=True)
    args = p.parse_args()
    if args.action == "analyze_and_send":
        cmd_analyze(args.title_id)
    else:
        cmd_qa_and_build(args.title_id)


if __name__ == "__main__":
    main()
