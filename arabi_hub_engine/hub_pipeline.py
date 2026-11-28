"""
PS5 Arabi Hub v2.0 — Universal Cloud Engine (Abdullah's 7 Rules + Auto-QA + Telegram Bot)
Works with ALL engines: Unreal (.pak/IoStore), Unity, RE Engine, Rockstar RAGE, FromSoftware, Generic.
"""

import argparse
import html
import json
import os
import re
from pathlib import Path

import requests

TOKEN_RE = re.compile(
    r"(~[^~\r\n]{1,40}~"
    r"|\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    r"|<[^>]+>"
    r"|%(?:\d+\$)?[+-]?(?:\d+)?(?:\.\d+)?[diuoxXfFeEgGaAcspn%]"
    r"|\[[A-Za-z0-9_:\-]+\])"
)

GEMINI_MASTER_PROMPT = """أنت مترجم ألعاب محترف متخصص في تعريب ألعاب PlayStation إلى العربية الفصحى الطبيعية السلسة.
المطلوب: ترجم قيم JSON التالية إلى العربية مع الالتزام الصارم بجميع القواعد:
1. أرجع ملف JSON صالح 100% بنفس المفاتيح بالضبط (لا تغيّر ولا تحذف أي مفتاح).
2. حافظ على جميع الرموز والمتغيرات والألوان والأزرار كما هي حرفياً دون ترجمة أو تعديل أو حذف أقواس: مثل ~b~ و ~s~ و ~n~ و %s و %d و {0} و <tag> و [BTN].
3. ترجم بأسلوب حوارات ألعاب طبيعي وممتع يناسب السياق، وتجنب الترجمة الحرفية (أسماء الشخصيات والأماكن تُعرّب صوتياً).
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
    if not token or not chat_id or not file_path.exists():
        return
    with file_path.open("rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption[:1000]},
            files={"document": (file_path.name, f)},
            timeout=60,
        )
    print(f"Telegram sendDocument {file_path.name}:", r.status_code, flush=True)


def analyze_file_tree(tree_text: str) -> list[str]:
    """Identify likely localization & font files across Unity, Unreal, RE, RAGE, Godot, Generic."""
    hits = []
    keywords = (
        ".locres", ".ufont", ".ttf", ".otf", "localization", "language", "lang",
        "subtitles", "dialog", "text", "string", "resources.assets", "globalgamemanagers",
        ".json", ".xml", ".csv", ".po", ".msg", ".fmg", ".gxt2", ".rpf",
    )
    for line in tree_text.splitlines():
        low = line.lower()
        if any(k in low for k in keywords):
            hits.append(line)
    return hits[:40]


def cmd_analyze(title_id: str):
    gdir = Path("hub_games") / title_id
    scan = json.loads((gdir / "scan.json").read_text(encoding="utf-8"))
    prompt_file = gdir / "PROMPT_GEMINI_AR.txt"
    prompt_file.write_text(GEMINI_MASTER_PROMPT, encoding="utf-8")

    extracted = gdir / "extracted.arabi"
    tree_path = gdir / "file_tree.txt"
    candidates_summary = ""

    if extracted.exists():
        raw = extracted.read_bytes()
        # If non-Unreal (file_tree text), save as file_tree.txt and analyze candidates!
        if scan.get("engine") != "Unreal Engine":
            tree_text = raw.decode("utf-8", errors="replace")
            tree_path.write_text(tree_text, encoding="utf-8")
            hits = analyze_file_tree(tree_text)
            if hits:
                candidates_summary = "\n\n📂 أبرز ملفات النصوص/الخطوط المرشّحة:\n" + "\n".join(hits[:12])

    msg = (
        f"🎮 تم استلام وفحص اللعبة بنجاح عبر PS5 Arabi Hub v2!\n"
        f"• الرمز: {title_id}\n"
        f"• المحرك: {scan.get('engine')}" + (f" (v{scan.get('ue_ver')})" if scan.get("ue_ver") else "") + "\n"
        f"• إجمالي الملفات: {scan.get('total_files', '?')}\n"
        f"• التشفير: {'مشفّر 🔒' if scan.get('encrypted') else 'غير مشفّر ✅'}"
        f"{candidates_summary}\n\n"
        f"✅ أرفقت لك شجرة ملفات اللعبة + البرومبت الاحترافي لجميني."
    )
    tg_send_message(msg)
    if tree_path.exists():
        tg_send_document(tree_path, f"شجرة ملفات {title_id} (أرسلها لجميني لتحديد ملفات النصوص بدقة 100%)")
    tg_send_document(prompt_file, "الأمر الاحترافي لجميني")


def cmd_qa_and_build(title_id: str):
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
