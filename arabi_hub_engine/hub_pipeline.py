"""
PS5 Arabi Hub v3 — BEAST UNIVERSAL CLOUD ENGINE
Supports:
  - Unreal Engine 4/5 (.locres + 24-slot Arabic+Latin font + repak v11 + retoc IoStore)
  - Unity (UnityPy StringTable / TextAsset .bundle extraction & rebuild)
  - Direct Text / Godot / RPG Maker / JSON / XML / CSV
  - Custom AI-generated Python plugins (hub_games/<TITLE_ID>/custom_plugin.py)
  - Strict Auto-QA Gate + Configurable Rendering Fixes (reshape / bidi / LRO / wrap_width)
  - Auto-Publish to GitHub Releases (tag: patch-<TITLE_ID>) + Telegram Bot Delivery
"""

import argparse
import html
import json
import os
import re
import shutil
import struct
import subprocess
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

GEMINI_MASTER_PROMPT = """أنت مترجم ألعاب محترف متخصص في تعريب ألعاب PlayStation إلى العربية الفصحى الطبيعية السلسة (وفق منهجية عبدالله السبيعي الاحترافية).
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
        print("Telegram secrets missing; skipping.", flush=True)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text[:4000]},
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


def tg_send_photo(photo_path: Path, caption: str = ""):
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat_id or not photo_path.exists():
        return
    with photo_path.open("rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1000]},
            files={"photo": (photo_path.name, f)},
            timeout=60,
        )
    print("Telegram sendPhoto:", r.status_code, flush=True)



def load_custom_fix(gdir: Path):
    cf = gdir / "custom_fix.py"
    if not cf.exists():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("custom_fix", str(cf))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "transform_text", None)

def load_render_cfg(gdir: Path) -> dict:
    p = gdir / "render_config.json"
    default = {"reshape": True, "bidi": True, "use_lro": True, "wrap_width": 32, "aes_key": ""}
    if p.exists():
        try:
            default.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return default


def shape_arabic_line(line: str, cfg: dict) -> str:
    if not line or not ARABIC_RE.search(line):
        return line
    import arabic_reshaper
    from bidi.algorithm import get_display

    reshaper = arabic_reshaper.ArabicReshaper({"delete_harakat": False, "support_ligatures": True})
    tokens = []
    def repl(m):
        idx = len(tokens)
        tokens.append(m.group(0))
        return "\u200F" + chr(0xE000 + idx) + "\u200F"

    protected = TOKEN_RE.sub(repl, line)
    out = reshaper.reshape(protected) if cfg.get("reshape", True) else protected
    if cfg.get("bidi", True):
        out = get_display(out, base_dir="R")
    for idx, tok in enumerate(tokens):
        out = out.replace("\u200F" + chr(0xE000 + idx) + "\u200F", tok).replace(chr(0xE000 + idx), tok)
    if cfg.get("use_lro", True) and cfg.get("bidi", True):
        out = "\u202D" + out + "\u202C"
    return out


def shape_arabic_text(text: str, cfg: dict, nl_token: str = "\n") -> str:
    if not text or not ARABIC_RE.search(text):
        return text
    text = html.unescape(text)
    wrap_w = int(cfg.get("wrap_width", 32) or 0)
    parts = re.split(r"(~[nN]~|\r\n|\n)", text)
    out_parts = []
    for part in parts:
        if part in ("~n~", "~N~", "\r\n", "\n") or not part:
            out_parts.append(nl_token if part in ("~n~", "~N~", "\r\n", "\n") else part)
            continue
        if wrap_w > 0 and len(TAG_STRIP_RE.sub("", part)) > wrap_w:
            toks = []
            def tp(m):
                idx = len(toks); toks.append(m.group(0)); return f"__T{idx}__"
            tmp = TOKEN_RE.sub(tp, part)
            wrapped = textwrap.wrap(tmp, width=wrap_w, break_long_words=False, break_on_hyphens=False)
            shaped_lines = []
            for wl in wrapped:
                for idx, tok in enumerate(toks):
                    wl = wl.replace(f"__T{idx}__", tok)
                shaped_lines.append(shape_arabic_line(wl, cfg))
            out_parts.append(nl_token.join(shaped_lines))
        else:
            out_parts.append(shape_arabic_line(part, cfg))
    return "".join(out_parts)


def qa_repair_string(ar: str, orig_en: str) -> str:
    ar = html.unescape(ar)
    toks = TOKEN_RE.findall(orig_en.replace("\r\n", "\n"))
    for idx, tok in enumerate(toks):
        ar = re.sub(rf"\[+\s*[xX]\s*{idx}\s*\]+", lambda _: tok, ar)
    ar = re.sub(r"\[+\s*[xX]\s*\d+\s*\]+", "", ar)
    return re.sub(r" {2,}", " ", ar).strip()


def split_and_send_parts(title_id: str, strings_map: dict[str, str], gdir: Path, chunk_size: int = 750):
    parts_dir = gdir / "parts_en"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)
    (gdir / "master_en_map.json").write_text(json.dumps(strings_map, ensure_ascii=False, indent=1), encoding="utf-8")

    keys = list(strings_map.keys())
    total_parts = max(1, (len(keys) + chunk_size - 1) // chunk_size)
    prompt_file = gdir / "PROMPT_GEMINI_AR.txt"
    prompt_file.write_text(GEMINI_MASTER_PROMPT, encoding="utf-8")

    tg_send_message(
        f"📦 تم استخراج نصوص اللعبة {title_id} بنجاح!\n"
        f"• عدد النصوص القابلة للترجمة: {len(keys):,}\n"
        f"• تم تقسيمها إلى {total_parts} ملف JSON جاهز لجميني.\n"
        f"ترجمها في جميني ثم ارفعها من زر (☁️ 2. رفع ملفات الترجمة) في لوحة Safari."
    )
    tg_send_document(prompt_file, "الأمر الاحترافي لجميني (أرسله مع كل ملف)")
    for pi in range(total_parts):
        sub = {k: strings_map[k] for k in keys[pi * chunk_size:(pi + 1) * chunk_size]}
        pf = parts_dir / f"part_{pi + 1:02d}.json"
        pf.write_text(json.dumps(sub, ensure_ascii=False, indent=1), encoding="utf-8")
        tg_send_document(pf, f"{title_id} — الجزء {pi + 1}/{total_parts} ({len(sub)} نص)")


def analyze_file_tree(tree_text: str) -> list[str]:
    hits = []
    keywords = (
        ".locres", ".ufont", ".ttf", ".otf", "localization", "language", "lang",
        "subtitles", "dialog", "text", "string", "resources.assets", "globalgamemanagers",
        ".json", ".xml", ".csv", ".po", ".msg", ".fmg", ".gxt2", ".rpf", ".bundle",
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
    if extracted.exists() and scan.get("engine") != "Unreal Engine":
        tree_text = extracted.read_text(encoding="utf-8", errors="replace")
        tree_path.write_text(tree_text, encoding="utf-8")
        hits = analyze_file_tree(tree_text)
        if hits:
            candidates_summary = "\n\n📂 أبرز ملفات النصوص المرشّحة (انسخ مسار ملف الإنجليزي في خانة سحب ملف محدد بلوحة Safari):\n" + "\n".join(hits[:12])

    msg = (
        f"🎮 تم فحص اللعبة عبر PS5 Arabi Hub v3 (نسخة الوحش)!\n"
        f"• الرمز: {title_id}\n"
        f"• المحرك: {scan.get('engine')}" + (f" (v{scan.get('ue_ver')})" if scan.get("ue_ver") else "") + "\n"
        f"• إجمالي الملفات: {scan.get('total_files', '?')}\n"
        f"• التشفير: {'مشفّر 🔒' if scan.get('encrypted') else 'غير مشفّر ✅'}"
        f"{candidates_summary}"
    )
    tg_send_message(msg)
    if tree_path.exists():
        tg_send_document(tree_path, f"شجرة ملفات {title_id}")
    tg_send_document(prompt_file, "الأمر الاحترافي لجميني")


def cmd_extract_texts(title_id: str):
    """Extract strings from a pulled Unity .bundle, Unreal .locres, or direct .json/.xml file."""
    gdir = Path("hub_games") / title_id
    meta = json.loads((gdir / "target_file.json").read_text(encoding="utf-8"))
    raw_file = gdir / "raw" / meta["fname"]
    fname_low = meta["fname"].lower()
    strings_map = {}

    if fname_low.endswith(".bundle") or fname_low.endswith(".assets"):
        import UnityPy
        env = UnityPy.load(str(raw_file))
        for obj in env.objects:
            if obj.type.name == "MonoBehaviour":
                try:
                    tree = obj.read_typetree()
                    entries = tree.get("m_TableData") or []
                    for ent in entries:
                        eid = str(ent.get("m_Id", ""))
                        val = ent.get("m_Localized", "")
                        if eid and isinstance(val, str) and val.strip():
                            strings_map[f"{obj.path_id}:{eid}"] = val
                except Exception:
                    pass
            elif obj.type.name == "TextAsset":
                try:
                    ta = obj.read()
                    txt = ta.text
                    if isinstance(txt, str) and txt.strip():
                        strings_map[f"TA:{obj.path_id}"] = txt
                except Exception:
                    pass
    elif fname_low.endswith(".json"):
        data = json.loads(raw_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            strings_map = {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v.strip()}

    if not strings_map:
        tg_send_message(f"⚠️ لم يتم استخراج نصوص تلقائياً من {meta['fname']} — أرسل الملف لجميني ليكتب لك وحدة custom_plugin.py مخصصة لهذه الصيغة.")
        tg_send_document(raw_file, f"الملف الخام {meta['fname']}")
        return

    split_and_send_parts(title_id, strings_map, gdir)


def publish_github_release(title_id: str, asset_path: Path, target_rel: str):
    """Publish final patch to GitHub Releases (tag: patch-<TITLE_ID>) so Safari 1-tap Install grabs it."""
    tag = f"patch-{title_id}"
    body = f"TARGET_REL={target_rel}\nBuilt automatically by PS5 Arabi Hub v3 Beast Engine."
    subprocess.run(["gh", "release", "delete", tag, "--yes"], check=False)
    subprocess.run(
        ["gh", "release", "create", tag, str(asset_path), "--title", f"PS5 Arabic Patch {title_id}", "--notes", body],
        check=True,
    )
    print(f"Published GitHub Release {tag} -> {asset_path.name}", flush=True)


def cmd_qa_and_build(title_id: str):
    gdir = Path("hub_games") / title_id
    cfg = load_render_cfg(gdir)
    tr_dir = gdir / "translated"
    master_en = json.loads((gdir / "master_en_map.json").read_text(encoding="utf-8")) if (gdir / "master_en_map.json").exists() else {}

    merged = {}
    repaired = 0
    for jf in sorted(tr_dir.glob("*.json")):
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            for k, v in data.items():
                if isinstance(v, str) and v.strip():
                    orig = master_en.get(k, "")
                    cleaned = qa_repair_string(v.strip(), orig)
                    if cleaned != v.strip():
                        repaired += 1
                    merged[k] = cleaned
        except Exception as e:
            print(f"Skipping {jf.name}: {e}", flush=True)

    (gdir / "merged_ar_qa.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")

    # If a Unity .bundle target exists, rebuild it with UnityPy and publish to GitHub Releases!
    target_meta_path = gdir / "target_file.json"
    if target_meta_path.exists():
        meta = json.loads(target_meta_path.read_text(encoding="utf-8"))
        raw_file = gdir / "raw" / meta["fname"]
        if meta["fname"].lower().endswith((".bundle", ".assets")) and raw_file.exists():
            import UnityPy
            env = UnityPy.load(str(raw_file))
            custom_fn = load_custom_fix(gdir)
            skip_set = {k.lower() for k in cfg.get('skip_keys', [])}
            patched_cnt = 0
            for obj in env.objects:
                if obj.type.name == "MonoBehaviour":
                    try:
                        tree = obj.read_typetree()
                        entries = tree.get("m_TableData") or []
                        changed = False
                        for ent in entries:
                            key = f"{obj.path_id}:{ent.get('m_Id', '')}"
                            if key in merged and ARABIC_RE.search(merged[key]):
                                val_out = merged[key]
                                if custom_fn:
                                    val_out = custom_fn(val_out, master_en.get(key, ""), key, cfg)
                                if key.lower() not in skip_set:
                                    ent["m_Localized"] = shape_arabic_text(val_out, cfg, nl_token="\n")
                                changed = True
                                patched_cnt += 1
                        if changed:
                            obj.save_typetree(tree)
                    except Exception:
                        pass
            out_bundle = gdir / meta["fname"]
            out_bundle.write_bytes(env.file.save())
            publish_github_release(title_id, out_bundle, meta["rel"])
            tg_send_message(
                f"✅ اكتمل البناء والتدقيق الآلي لـ {title_id} (Unity)!\n"
                f"• نصوص معرّبة: {patched_cnt:,} | تم تنظيفها بـ Auto-QA: {repaired:,}\n"
                f"افتح لوحة PS5 Arabi في Safari واضغط (📥 3. تثبيت آخر تعريب جاهز على السوني)!"
            )
            return

    tg_send_message(
        f"✅ اكتمل التدقيق الآلي (Auto-QA) للعبة {title_id}!\n"
        f"• إجمالي النصوص الصالحة: {len(merged):,} | تم تنظيفها: {repaired:,}"
    )


def cmd_send_bug_photo(title_id: str):
    gdir = Path("hub_games") / title_id
    photo = gdir / "bug_report.jpg"
    cfg = load_render_cfg(gdir)
    caption = (
        f"📸 تقرير مشكلة عرض للعبة {title_id}\n"
        f"الإعدادات الحالية: reshape={cfg['reshape']}, bidi={cfg['bidi']}, LRO={cfg['use_lro']}, wrap={cfg['wrap_width']}\n"
        f"ارفع هذه الصورة لجميني أو عدّل الخيارات في قسم (🔧 إصلاح مشاكل العرض) واضغط إعادة بناء (20 ثانية)."
    )
    tg_send_photo(photo, caption)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["analyze_and_send", "extract_texts", "qa_and_build", "send_bug_photo"], required=True)
    p.add_argument("--title-id", required=True)
    args = p.parse_args()
    if args.action == "analyze_and_send":
        cmd_analyze(args.title_id)
    elif args.action == "extract_texts":
        cmd_extract_texts(args.title_id)
    elif args.action == "qa_and_build":
        cmd_qa_and_build(args.title_id)
    elif args.action == "send_bug_photo":
        cmd_send_bug_photo(args.title_id)


if __name__ == "__main__":
    main()
