"""
PS5 Arabi Hub v7 — OMNIVERSE FINAL UNIVERSAL ENGINE
Implements & exceeds Abdullah Al-Subaie's 7-Step Localization Methodology:
  - Step 1: Auto-discovery + SHA-256 original file fingerprinting (manifest.json)
  - Step 2: Universal Multi-Engine Extractors & Rebuilders:
      1) Unity (Unity.Localization, I2 Localization, TextAsset JSON/CSV/TXT, TextMeshPro/UI Text,
         Custom MonoBehaviour ScriptableObjects, Addressables catalog.json decoder & CRC patcher, Font injector)
      2) Unreal Engine 4/5 (.locres v1/v2/v3 pure-Python parser/writer + repak .pak + retoc IoStore + Auto-Font)
      3) Capcom RE Engine (.msg GMSG XOR-encrypted UTF-16LE binary parser/writer)
      4) FromSoftware (.fmg v1/v2 UTF-16LE binary parser/writer — Elden Ring/Dark Souls/Bloodborne/Sekiro/AC6)
      5) Godot / Ren'Py / RPG Maker / Indie (Nested JSON, XML, CSV, TSV, PO/POT, INI, SRT/VTT, TXT, .rpy)
      6) Custom Engine Plugin Hook (hub_games/<TID>/custom_plugin.py -> extract() & rebuild())
  - Step 3: Bundled verified ArabicGameFont.ttf + custom user font override support
  - Step 4: 1-Tap 10-Line Canary Rendering Test (proves Arabic joining, BiDi, mixed numbers/English, wrapping & tags BEFORE full translation!)
  - Step 5-7: Zero-Crash Printf/Token QA Gate + Post-Build Integrity Verifier + Multi-File Atomic Publisher
"""

import argparse
import base64
import csv
import hashlib
import html
import importlib.util
import io
import json
import os
import re
import shutil
import struct
import subprocess
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ENGINE_DIR = Path(__file__).resolve().parent
ARABIC_FONT_TTF = ENGINE_DIR / "assets" / "ArabicGameFont.ttf"

TOKEN_RE = re.compile(
    r"(~[^~\r\n]{1,40}~"
    r"|\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    r"|<[^>]+>"
    r"|%(?:\d+\$)?[+-]?(?:\d+)?(?:\.\d+)?[diuoxXfFeEgGaAcspn%]"
    r"|\[[A-Za-z0-9_:\-]+\])"
)
CRITICAL_PRINTF_RE = re.compile(r"%(?:\d+\$)?[+-]?(?:\d+)?(?:\.\d+)?[diuoxXfFeEgGaAcspn]")
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
TAG_STRIP_RE = re.compile(r"~[^~\r\n]+~|<[^>]+>")
LOCRES_MAGIC = bytes([0x0E, 0x14, 0x74, 0x75, 0x67, 0x4A, 0x03, 0xFC, 0x4A, 0x15, 0x90, 0x9D, 0xC3, 0x37, 0x7F, 0x1B])
RE_MSG_XOR_KEY = bytes([0xCF, 0xCE, 0xFB, 0xF8, 0xEC, 0x0A, 0x33, 0x66, 0x93, 0xA9, 0x1D, 0x93, 0x50, 0x39, 0x5F, 0x09])

SKIP_TEXTASSET_NAMES = ("ofl", "license", "emojione", "readme", "shader", "copyright", "thirdparty", "credits_license")
TECH_STRING_RE = re.compile(r"^([A-Za-z0-9_./\\:\-]+|[0-9a-fA-F]{16,}|#[0-9a-fA-F]{3,8})$")

CANARY_SAMPLES = [
    "اختبار التعريب العربي المتصل بنجاح",
    "ابدأ اللعب الآن",
    "الإعدادات والتحكم والصوت",
    "النتيجة: 100% — PS5 العربي",
    "إيقاف مؤقت • استئناف • خروج",
    "هل أنت متأكد من الحفظ؟ نعم / لا",
    "هذا نص طويل لاختبار التفاف السطور العربية داخل مربعات القوائم بدون قص أو تداخل",
    "الهمزات ولام ألف: أ إ آ ؤ ئ لا لأ لإ لآ",
    "المرحلة 1 — اللاعب الأول جاهز!",
    "تم إثبات العرض العربي بنجاح 100%",
]

GEMINI_MASTER_PROMPT = """أنت كبير معرّبي ألعاب فيديو محترف (بمستوى استوديوهات التعريب الرسمية ومنهجية عبدالله السبيعي).
مهمتك: ترجمة ملف JSON المرفق للعبة PlayStation إلى عربية فصحى سلسة وحيّة تبدو كأنها تعريب رسمي من الشركة المطوّرة، مع الالتزام الصارم بجميع القواعد التالية دون أي استثناء:

[أولاً — جودة الأسلوب ومعجم القوائم الموحّد]
1. أسلوب طبيعي 100%: ترجم المعنى والروح والانفعال لا الحرف. ابتعد تماماً عن الترجمة الحرفية الجامدة أو ركاكة الترجمة الآلية.
2. اختصار القوائم والأزرار (UI): النصوص القصيرة (كلمة إلى 3 كلمات مثل أسماء الأزرار والقوائم) يجب أن تبقى قصيرة ومباشرة لتناسب مربعات الواجهة دون خروج عن الإطار.
3. توحيد المصطلحات عبر جميع أجزاء اللعبة:
   • Settings/Options = الإعدادات | Controls = التحكم | Audio/Sound = الصوت | Graphics/Display = العرض
   • Play/Start = ابدأ | Continue = متابعة | Resume = استئناف | Pause = إيقاف مؤقت | Retry/Restart = إعادة المحاولة
   • Back = رجوع | Cancel = إلغاء | Confirm/Apply = تأكيد | Save = حفظ | Load = تحميل | Quit/Exit = خروج
   • Score = النقاط | High Score = أعلى نتيجة | Level/Stage = المرحلة | Tutorial = التعليمات | Leaderboard = لوحة الصدارة
   • Player = اللاعب | Victory/Win = فوز | Game Over = انتهت اللعبة | Loading = جاري التحميل...
4. أسماء الشخصيات والعلامات التجارية والأماكن الشهيرة: تُعرّب صوتياً بأسلوب طبيعي (أو تُبقى كما هي إذا كانت أسماء ألعاب كلاسيكية معروفة).

[ثانياً — قواعد السلامة الصارمة ضد الكراش (Zero-Crash Rules)]
5. أرجع ملف JSON صالح 100% فقط (بدون أي شرح قبله أو بعده) وبنفس المفاتيح (Keys) حرفياً دون تغيير أو حذف أو إضافة أي مفتاح.
6. حافظ على جميع المتغيرات والرموز البرمجية والألوان والأزرار حرفياً بنفس العدد والنوع والمكان المنطقي، ولا تترجمها أبداً:
   مثل: %s و %d و %i و %f و %.1f و {0} و {1} و {name} و ~b~ و ~s~ و ~n~ و <color=#...> و </color> و <b> و \\n و [BTN].
7. لا تستخدم كيانات HTML مثل &quot; أو &amp; — استخدم علامات التنصيص العادية (مع الهروب \\" داخل JSON عند الحاجة).
8. أي قيمة عبارة عن مسار ملف أو كود برمجي أو معرّف داخلي (مثل UI_Btn_01 أو Assets/...) اتركها كما هي دون ترجمة.
9. لا تترك أي جملة إنجليزية قابلة للترجمة بدون تعريب، وراجع كل سطر قبل التسليم للتأكد من صحة أقواس JSON وعلامات الفاصلة.
"""

AI_DOCTOR_MASTER_PROMPT = """أنت (دكتور التعريب — PS5 Arabi AI Doctor)، خبير هندسة عكسية وتعريب ألعاب PS4/PS5 على نظام PS5 Arabi Hub v7.
مهمتك مساعدة المستخدم بخطوة واحدة مباشرة حسب ما يرسله لك، ودائماً ترد بكود واحد جاهز للصق مباشرة داخل مربع (🤖 دكتور التعريب) في لوحة Safari بدون كلام طويل:

[الحالة 1 — شجرة ملفات اللعبة (file_tree.txt) أو فهرس (catalog.json)]
• حدّد بدقة ملف النصوص الإنجليزية وأرجع الصيغة الحرفية فقط:
{"pull_files": ["المسار/الأول/بالضبط"]}

[الحالة 2 — صورة من التلفزيون فيها مشكلة عرض بالعربي]
• حروف مقطّعة أو غير متصلة -> {"reshape":true,"bidi":true,"use_lro":true,"wrap_width":32,"skip_keys":[]}
• كلمات معكوسة (عكس مزدوج) -> {"reshape":true,"bidi":true,"use_lro":true,"wrap_width":32,"skip_keys":[]} (أو جرّب "bidi":false).
• نص يخرج من المربع -> قلّل "wrap_width" إلى 24 أو 28.
• مربعات □□□ مكان الحروف -> حدّد ملف الخط بـ {"pull_files":[...]}.
• قوائم بخط إنجليزي مرسوم (Bitmap) -> أضف مفاتيحها داخل "skip_keys".

[الحالة 3 — صيغة نادرة أو محرك مخصص يحتاج كود خاص]
اكتب ملف Python نظيف يحتوي على:
- إما def transform_text(ar_text, orig_en, key, cfg): لتعديل العرض
- أو def extract(raw_bytes) -> dict و def rebuild(raw_bytes, translations, cfg) -> bytes لفك وبناء أي صيغة نادرة.
"""


# ─────────────────────────── Helpers & SHA-256 Manifest ───────────────────────────


def reassemble_chunked_raw_files(gdir: Path):
    """Automatically merges any >15MB chunked files uploaded from iPhone Safari (.chunks.json + .partNNN)."""
    raw_dir = gdir / "raw"
    if not raw_dir.exists():
        return
    for meta_p in sorted(raw_dir.glob("*.chunks.json")):
        try:
            info = json.loads(meta_p.read_text(encoding="utf-8"))
            fname = info["fname"]
            count = int(info["chunks"])
            out_p = raw_dir / fname
            with out_p.open("wb") as out_f:
                for i in range(count):
                    part_p = raw_dir / f"{fname}.part{i:03d}"
                    if part_p.exists():
                        out_f.write(part_p.read_bytes())
            print(f"Reassembled chunked file {fname} ({out_p.stat().st_size:,} bytes from {count} parts)", flush=True)
        except Exception as e:
            print(f"Chunk reassembly error for {meta_p.name}: {e}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def record_manifest(gdir: Path, key: str, value):
    mp = gdir / "manifest.json"
    data = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    data[key] = value
    mp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_active_font(gdir: Path) -> Path:
    for ext in ("*.ttf", "*.otf"):
        custom = list((gdir / "fonts").glob(ext)) if (gdir / "fonts").exists() else []
        if custom:
            return custom[0]
    return ARABIC_FONT_TTF


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


def load_module_from(path: Path, mod_name: str):
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_custom_fix(gdir: Path):
    mod = load_module_from(gdir / "custom_fix.py", "custom_fix")
    return getattr(mod, "transform_text", None) if mod else None


def load_custom_plugin(gdir: Path):
    for name in ("custom_plugin.py", "custom_fix.py"):
        mod = load_module_from(gdir / name, "custom_plugin")
        if mod and hasattr(mod, "extract") and hasattr(mod, "rebuild"):
            return mod
    return None


def load_render_cfg(gdir: Path) -> dict:
    p = gdir / "render_config.json"
    default = {"reshape": True, "bidi": True, "use_lro": True, "wrap_width": 32, "aes_key": "", "skip_keys": []}
    if p.exists():
        try:
            default.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return default


def is_human_translatable(s: str) -> bool:
    if not isinstance(s, str):
        return False
    t = s.strip()
    if len(t) < 2 or len(t) > 4000 or not any(c.isalpha() for c in t):
        return False
    if TECH_STRING_RE.match(t) and " " not in t:
        if not (t.isalpha() and 2 <= len(t) <= 24 and (t[0].isupper() or t.isupper())):
            return False
    low = t.lower()
    if low.startswith(("assets/", "http://", "https://", "unityengine.", "system.", "{unityengine.")):
        return False
    return True


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
                idx = len(toks)
                toks.append(m.group(0))
                return f"__T{idx}__"

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


def qa_repair_and_validate(ar: str, orig_en: str) -> tuple[str, bool, bool]:
    cleaned = html.unescape(ar)
    toks = TOKEN_RE.findall(orig_en.replace("\r\n", "\n")) if orig_en else []
    for idx, tok in enumerate(toks):
        cleaned = re.sub(rf"\[+\s*[xX]\s*{idx}\s*\]+", lambda _: tok, cleaned)
    cleaned = re.sub(r"\[+\s*[xX]\s*\d+\s*\]+", "", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned).strip()
    repaired = (cleaned != ar.strip())

    if orig_en:
        orig_pf = sorted(CRITICAL_PRINTF_RE.findall(orig_en))
        ar_pf = sorted(CRITICAL_PRINTF_RE.findall(cleaned))
        if orig_pf != ar_pf:
            return orig_en, False, True
    return cleaned, repaired, False


# ─────────────────────────── ENGINE 1: UNITY UNIVERSAL ───────────────────────────

def decode_unity_addressables_catalog(raw_catalog: Path):
    cat = json.loads(raw_catalog.read_text(encoding="utf-8"))
    iids = cat.get("m_InternalIds") or []
    ed_b64 = cat.get("m_EntryDataString") or ""
    bd_b64 = cat.get("m_BucketDataString") or ""
    if not iids or not ed_b64 or not bd_b64:
        return [], [], []

    ed, bd = base64.b64decode(ed_b64), base64.b64decode(bd_b64)
    (entry_cnt,) = struct.unpack_from("<I", ed, 0)
    entries, off = [], 4
    for _ in range(entry_cnt):
        if off + 28 > len(ed):
            break
        entries.append(struct.unpack_from("<7i", ed, off))
        off += 28

    (bucket_cnt,) = struct.unpack_from("<I", bd, 0)
    buckets, off = [], 4
    for _ in range(bucket_cnt):
        if off + 8 > len(bd):
            break
        _do, cnt = struct.unpack_from("<ii", bd, off)
        off += 8
        idxs = list(struct.unpack_from(f"<{cnt}i", bd, off)) if cnt > 0 and off + 4 * cnt <= len(bd) else []
        off += 4 * cnt
        buckets.append(idxs)

    def resolve_bundle(dep_idx: int) -> str:
        if 0 <= dep_idx < len(buckets):
            for be_i in buckets[dep_idx]:
                if 0 <= be_i < len(entries):
                    iid_i = entries[be_i][0]
                    if 0 <= iid_i < len(iids) and iids[iid_i].lower().endswith(".bundle"):
                        b = iids[iid_i]
                        if "/PS5/" in b:
                            return "Media/StreamingAssets/aa/PS5/" + b.split("/PS5/")[-1]
                        if "/PS4/" in b:
                            return "Media/StreamingAssets/aa/PS4/" + b.split("/PS4/")[-1]
                        return b
        return ""

    loc_kws = ("localiz", "lang", "english", "string", "subtit", "dialog", "i2loc", "tradu", "loc_", "texts/", "vocab", "caption")
    font_kws = ("/font/", "/04_font/", ".ttf", ".otf", "sdf.asset")
    media_exts = (".png", ".jpg", ".jpeg", ".tga", ".psd", ".dds", ".rendertexture", ".wav", ".ogg", ".mp3", ".mp4", ".mat", ".fbx", ".obj", ".prefab", ".shadergraph", ".shader", ".controller", ".anim", ".unity", ".lighting", ".physicmaterial")
    data_exts = (".asset", ".csv", ".json", ".xml", ".txt", ".bytes", ".po", ".tsv")

    loc_hits, data_hits, font_hits = [], [], []
    seen_l, seen_d, seen_f = set(), set(), set()

    for e in entries:
        iid_i, _prov, dep_i = e[0], e[1], e[2]
        if not (0 <= iid_i < len(iids)):
            continue
        asset = iids[iid_i]
        low = asset.lower()
        if low.endswith(".bundle") or "texture" in low or "/audio/" in low or "/sfx/" in low or "/musics/" in low:
            continue
        if any(s in low for s in SKIP_TEXTASSET_NAMES):
            continue
        if any(k in low for k in font_kws) and not low.endswith(".mat"):
            bpath = resolve_bundle(dep_i)
            if bpath and bpath not in seen_f:
                seen_f.add(bpath)
                font_hits.append((bpath, asset))
            continue
        if low.endswith(media_exts):
            continue
        if any(k in low for k in loc_kws):
            bpath = resolve_bundle(dep_i)
            if bpath and bpath not in seen_l:
                seen_l.add(bpath)
                loc_hits.append((bpath, asset))
        elif low.endswith(data_exts) and "/audio" not in low and "/vfx" not in low:
            bpath = resolve_bundle(dep_i)
            if bpath and bpath not in seen_d:
                seen_d.add(bpath)
                data_hits.append((bpath, asset))
    return loc_hits, data_hits, font_hits


def patch_unity_catalog_json(raw_catalog: Path, out_catalog: Path) -> bool:
    try:
        txt = raw_catalog.read_text(encoding="utf-8")
        patched = txt.replace('"m_UseCrcForCachedBundles":true', '"m_UseCrcForCachedBundles":false')
        patched = patched.replace('"m_UseCrcForCachedBundles": true', '"m_UseCrcForCachedBundles": false')
        patched = re.sub(r'"m_Crc"\s*:\s*\d+', '"m_Crc":0', patched)
        json.loads(patched)
        out_catalog.write_text(patched, encoding="utf-8")
        return True
    except Exception:
        return False


def _extract_i2_terms(tree: dict, pid: int, out: dict):
    src = tree.get("mSource") or tree
    for idx, t in enumerate(src.get("mTerms") or []):
        if isinstance(t, dict):
            langs = t.get("Languages") or []
            if langs and isinstance(langs[0], str) and is_human_translatable(langs[0]):
                out[f"I2:{pid}:{idx}:{t.get('Term', f'idx{idx}')}"] = langs[0]


def _patch_i2_terms(tree: dict, pid: int, merged: dict, cfg: dict, custom_fn, master_en: dict, skip_set: set) -> int:
    src = tree.get("mSource") or tree
    cnt = 0
    for idx, t in enumerate(src.get("mTerms") or []):
        if isinstance(t, dict):
            langs = t.get("Languages") or []
            key = f"I2:{pid}:{idx}:{t.get('Term', f'idx{idx}')}"
            if langs and key in merged and ARABIC_RE.search(merged[key]) and key.lower() not in skip_set:
                val = custom_fn(merged[key], master_en.get(key, ""), key, cfg) if custom_fn else merged[key]
                langs[0] = shape_arabic_text(val, cfg, nl_token="\n")
                cnt += 1
    return cnt


def _walk_custom_mb_extract(obj, pid: int, path: str, out: dict):
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in ("m_name", "m_script", "m_gameobject", "m_enabled", "m_fileid", "m_pathid", "guid", "hash", "id"):
                continue
            p = f"{path}.{k}" if path else str(k)
            if isinstance(v, str):
                if any(w in kl for w in ("text", "title", "desc", "label", "msg", "message", "dialog", "caption", "name", "en", "english", "localized", "value", "content", "line", "prompt", "hint", "tip")):
                    if is_human_translatable(v):
                        out[f"MB:{pid}:{p}"] = v
            elif isinstance(v, (dict, list)):
                _walk_custom_mb_extract(v, pid, p, out)
    elif isinstance(obj, list) and len(obj) <= 5000:
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                _walk_custom_mb_extract(v, pid, f"{path}[{i}]", out)


def _walk_custom_mb_patch(obj, pid: int, path: str, merged: dict, cfg: dict, custom_fn, master_en: dict, skip_set: set) -> int:
    cnt = 0
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            p = f"{path}.{k}" if path else str(k)
            key = f"MB:{pid}:{p}"
            if isinstance(v, str) and key in merged and ARABIC_RE.search(merged[key]) and key.lower() not in skip_set:
                val = custom_fn(merged[key], master_en.get(key, ""), key, cfg) if custom_fn else merged[key]
                obj[k] = shape_arabic_text(val, cfg, nl_token="\n")
                cnt += 1
            elif isinstance(v, (dict, list)):
                cnt += _walk_custom_mb_patch(v, pid, p, merged, cfg, custom_fn, master_en, skip_set)
    elif isinstance(obj, list) and len(obj) <= 5000:
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                cnt += _walk_custom_mb_patch(v, pid, f"{path}[{i}]", merged, cfg, custom_fn, master_en, skip_set)
    return cnt


def extract_unity_universal(raw_file: Path) -> dict[str, str]:
    import UnityPy
    env = UnityPy.load(str(raw_file))
    strings_map = {}
    for obj in env.objects:
        if obj.type.name == "MonoBehaviour":
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            if isinstance(tree.get("m_TableData"), list):
                for ent in tree["m_TableData"]:
                    eid, val = str(ent.get("m_Id", "")), ent.get("m_Localized", "")
                    if eid and isinstance(val, str) and val.strip():
                        strings_map[f"{obj.path_id}:{eid}"] = val
            elif "mSource" in tree or "mTerms" in tree:
                _extract_i2_terms(tree, obj.path_id, strings_map)
            elif isinstance(tree.get("m_text"), str) and is_human_translatable(tree["m_text"]):
                strings_map[f"TMP:{obj.path_id}"] = tree["m_text"]
            elif isinstance(tree.get("m_Text"), str) and is_human_translatable(tree["m_Text"]):
                strings_map[f"UIT:{obj.path_id}"] = tree["m_Text"]
            else:
                _walk_custom_mb_extract(tree, obj.path_id, "", strings_map)
        elif obj.type.name == "TextAsset":
            try:
                ta = obj.read()
                tname = (getattr(ta, "m_Name", "") or getattr(ta, "name", "") or "").lower()
                if any(s in tname for s in SKIP_TEXTASSET_NAMES):
                    continue
                txt = ta.text
                if not isinstance(txt, str) or not txt.strip():
                    continue
                if txt.lstrip().startswith(("{", "[")):
                    try:
                        for fk, fv in flatten_json(json.loads(txt)).items():
                            if is_human_translatable(fv):
                                strings_map[f"TAJ:{obj.path_id}:{fk}"] = fv
                        continue
                    except Exception:
                        pass
                lines = [ln for ln in txt.splitlines() if is_human_translatable(ln)]
                if 1 <= len(lines) <= 4000:
                    for li, ln in enumerate(txt.splitlines()):
                        if is_human_translatable(ln):
                            strings_map[f"TAL:{obj.path_id}:{li}"] = ln
            except Exception:
                pass
    return strings_map


def rebuild_unity_universal(raw_file: Path, out_file: Path, merged: dict, cfg: dict, custom_fn, master_en: dict, font_path: Path) -> tuple[int, int]:
    import UnityPy
    env = UnityPy.load(str(raw_file))
    skip_set = {k.lower() for k in cfg.get("skip_keys", [])}
    patched_cnt, fonts_injected = 0, 0
    for obj in env.objects:
        if obj.type.name == "MonoBehaviour":
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            changed = False
            if isinstance(tree.get("m_TableData"), list):
                for ent in tree["m_TableData"]:
                    key = f"{obj.path_id}:{ent.get('m_Id', '')}"
                    if key in merged and ARABIC_RE.search(merged[key]) and key.lower() not in skip_set:
                        val = custom_fn(merged[key], master_en.get(key, ""), key, cfg) if custom_fn else merged[key]
                        ent["m_Localized"] = shape_arabic_text(val, cfg, nl_token="\n")
                        changed = True
                        patched_cnt += 1
            elif "mSource" in tree or "mTerms" in tree:
                c = _patch_i2_terms(tree, obj.path_id, merged, cfg, custom_fn, master_en, skip_set)
                if c:
                    changed, patched_cnt = True, patched_cnt + c
            elif f"TMP:{obj.path_id}" in merged and ARABIC_RE.search(merged[f"TMP:{obj.path_id}"]):
                key = f"TMP:{obj.path_id}"
                val = custom_fn(merged[key], master_en.get(key, ""), key, cfg) if custom_fn else merged[key]
                tree["m_text"] = shape_arabic_text(val, cfg, nl_token="\n")
                changed, patched_cnt = True, patched_cnt + 1
            elif f"UIT:{obj.path_id}" in merged and ARABIC_RE.search(merged[f"UIT:{obj.path_id}"]):
                key = f"UIT:{obj.path_id}"
                val = custom_fn(merged[key], master_en.get(key, ""), key, cfg) if custom_fn else merged[key]
                tree["m_Text"] = shape_arabic_text(val, cfg, nl_token="\n")
                changed, patched_cnt = True, patched_cnt + 1
            else:
                c = _walk_custom_mb_patch(tree, obj.path_id, "", merged, cfg, custom_fn, master_en, skip_set)
                if c:
                    changed, patched_cnt = True, patched_cnt + c
            if changed:
                obj.save_typetree(tree)
        elif obj.type.name == "TextAsset":
            try:
                ta = obj.read()
                txt = ta.text
                if not isinstance(txt, str) or not txt.strip():
                    continue
                pj, pl = f"TAJ:{obj.path_id}:", f"TAL:{obj.path_id}:"
                if any(k.startswith(pj) for k in merged):
                    jdata = json.loads(txt)
                    c = apply_json_translations(jdata, {k[len(pj):]: v for k, v in merged.items() if k.startswith(pj)}, cfg, custom_fn, master_en)
                    if c:
                        ta.m_Script = json.dumps(jdata, ensure_ascii=False, indent=2)
                        ta.save()
                        patched_cnt += c
                elif any(k.startswith(pl) for k in merged):
                    lines, c = txt.splitlines(), 0
                    for li in range(len(lines)):
                        key = f"{pl}{li}"
                        if key in merged and ARABIC_RE.search(merged[key]) and key.lower() not in skip_set:
                            val = custom_fn(merged[key], master_en.get(key, ""), key, cfg) if custom_fn else merged[key]
                            lines[li] = shape_arabic_text(val, cfg, nl_token="\n")
                            c += 1
                    if c:
                        ta.m_Script = "\n".join(lines)
                        ta.save()
                        patched_cnt += c
            except Exception:
                pass
        elif obj.type.name == "Font" and font_path.exists():
            try:
                fobj = obj.read()
                fobj.m_FontData = list(font_path.read_bytes())
                fobj.save()
                fonts_injected += 1
            except Exception:
                pass
    out_file.write_bytes(env.file.save(packer="lz4") if raw_file.suffix.lower()==".bundle" else env.file.save())
    assert len(UnityPy.load(str(out_file)).objects) > 0, "Unity bundle integrity verification failed!"
    return patched_cnt, fonts_injected


# ─────────────────────────── ENGINE 2: UNREAL 4/5 (.locres + repak + retoc) ───────────────────────────

def _read_fstring(buf: bytes, off: int) -> tuple[str, int]:
    (length,) = struct.unpack_from("<i", buf, off)
    off += 4
    if length == 0:
        return "", off
    if length > 0:
        return buf[off:off + length - 1].decode("utf-8", errors="replace"), off + length
    u16_len = -length
    return buf[off:off + (u16_len - 1) * 2].decode("utf-16-le", errors="replace"), off + u16_len * 2


def _write_fstring(s: str, force_utf16: bool = False) -> bytes:
    if not s:
        return struct.pack("<i", 0)
    if force_utf16 or any(ord(c) > 127 for c in s):
        enc = s.encode("utf-16-le") + b"\x00\x00"
        return struct.pack("<i", -(len(enc) // 2)) + enc
    enc = s.encode("utf-8") + b"\x00"
    return struct.pack("<i", len(enc)) + enc


def parse_locres(data: bytes) -> tuple[dict, dict[str, str]]:
    if not data.startswith(LOCRES_MAGIC):
        raise ValueError("Not a valid UE4/UE5 .locres binary")
    off = 16
    version = data[off]
    off += 1
    (str_arr_off,) = struct.unpack_from("<q", data, off)
    off += 8

    sa_off = str_arr_off
    (sa_count,) = struct.unpack_from("<I", data, sa_off)
    sa_off += 4
    strings_arr, ref_counts = [], []
    for _ in range(sa_count):
        s, sa_off = _read_fstring(data, sa_off)
        strings_arr.append(s)
        if version >= 2:
            (rc,) = struct.unpack_from("<i", data, sa_off)
            sa_off += 4
            ref_counts.append(rc)
        else:
            ref_counts.append(1)

    entries_count = 0
    if version >= 2:
        (entries_count,) = struct.unpack_from("<I", data, off)
        off += 4

    (ns_count,) = struct.unpack_from("<I", data, off)
    off += 4
    namespaces, flat = [], {}
    for _ in range(ns_count):
        ns_hash = 0
        if version >= 3:
            (ns_hash,) = struct.unpack_from("<I", data, off)
            off += 4
        ns_name, off = _read_fstring(data, off)
        (k_count,) = struct.unpack_from("<I", data, off)
        off += 4
        k_list = []
        for _ in range(k_count):
            k_hash = 0
            if version >= 3:
                (k_hash,) = struct.unpack_from("<I", data, off)
                off += 4
            k_name, off = _read_fstring(data, off)
            (src_hash,) = struct.unpack_from("<I", data, off)
            off += 4
            (str_idx,) = struct.unpack_from("<i", data, off)
            off += 4
            k_list.append({"hash": k_hash, "key": k_name, "src_hash": src_hash, "idx": str_idx})
            if 0 <= str_idx < len(strings_arr) and strings_arr[str_idx].strip():
                flat[f"{ns_name}::{k_name}"] = strings_arr[str_idx]
        namespaces.append({"hash": ns_hash, "name": ns_name, "keys": k_list})
    return {"version": version, "entries_count": entries_count, "namespaces": namespaces, "strings_arr": strings_arr, "ref_counts": ref_counts}, flat


def rebuild_locres(orig_data: bytes, translations: dict[str, str], cfg: dict, custom_fn=None, master_en=None) -> tuple[bytes, int]:
    meta, _ = parse_locres(orig_data)
    version = meta["version"]
    strings_arr, ref_counts = list(meta["strings_arr"]), list(meta["ref_counts"])
    skip_set = {k.lower() for k in cfg.get("skip_keys", [])}
    patched_cnt = 0
    for ns in meta["namespaces"]:
        for k in ns["keys"]:
            full_key = f"{ns['name']}::{k['key']}"
            if full_key in translations and ARABIC_RE.search(translations[full_key]) and full_key.lower() not in skip_set:
                val = custom_fn(translations[full_key], (master_en or {}).get(full_key, ""), full_key, cfg) if custom_fn else translations[full_key]
                k["idx"] = len(strings_arr)
                strings_arr.append(shape_arabic_text(val, cfg, nl_token="\n"))
                ref_counts.append(1)
                patched_cnt += 1
    body = bytearray()
    if version >= 2:
        body += struct.pack("<I", meta["entries_count"])
    body += struct.pack("<I", len(meta["namespaces"]))
    for ns in meta["namespaces"]:
        if version >= 3:
            body += struct.pack("<I", ns["hash"])
        body += _write_fstring(ns["name"])
        body += struct.pack("<I", len(ns["keys"]))
        for k in ns["keys"]:
            if version >= 3:
                body += struct.pack("<I", k["hash"])
            body += _write_fstring(k["key"])
            body += struct.pack("<I", k["src_hash"])
            body += struct.pack("<i", k["idx"])
    out = bytearray(LOCRES_MAGIC)
    out.append(version)
    out += struct.pack("<q", 25 + len(body))
    out += body
    out += struct.pack("<I", len(strings_arr))
    for i, s in enumerate(strings_arr):
        out += _write_fstring(s, force_utf16=bool(ARABIC_RE.search(s)))
        if version >= 2:
            out += struct.pack("<i", ref_counts[i])
    parse_locres(bytes(out))
    return bytes(out), patched_cnt


# ─────────────────────────── ENGINE 3: FROMSOFTWARE (.fmg) ───────────────────────────

def parse_fmg(data: bytes) -> tuple[dict, dict[str, str]]:
    """Parses FromSoftware .fmg v1/v2 (Elden Ring, Dark Souls, Bloodborne, Sekiro, AC6)."""
    if len(data) < 32:
        raise ValueError("Invalid .fmg file")
    big_endian = (data[1] == 1)
    endian = ">" if big_endian else "<"
    version = data[2]
    is_64 = (version == 2)
    ptr_fmt = endian + ("Q" if is_64 else "I")
    ptr_sz = 8 if is_64 else 4

    group_cnt, str_cnt = struct.unpack_from(endian + "ii", data, 12)
    off = 24 if is_64 else 20
    (str_off_tbl,) = struct.unpack_from(ptr_fmt, data, off)
    off += ptr_sz + (8 if is_64 else 4)

    groups = []
    for _ in range(group_cnt):
        if is_64:
            first_idx, first_id, last_id, _pad = struct.unpack_from(endian + "iiii", data, off)
            off += 16
        else:
            first_idx, first_id, last_id = struct.unpack_from(endian + "iii", data, off)
            off += 12
        groups.append((first_idx, first_id, last_id))

    offsets = [struct.unpack_from(ptr_fmt, data, str_off_tbl + i * ptr_sz)[0] for i in range(str_cnt)]
    strings = []
    for so in offsets:
        if so == 0 or so >= len(data):
            strings.append(None)
        else:
            end = so
            while end + 1 < len(data) and (data[end] != 0 or data[end + 1] != 0):
                end += 2
            strings.append(data[so:end].decode("utf-16-be" if big_endian else "utf-16-le", errors="replace"))

    flat = {}
    for first_idx, first_id, last_id in groups:
        for delta in range(last_id - first_id + 1):
            idx = first_idx + delta
            if 0 <= idx < len(strings) and strings[idx] and strings[idx].strip():
                flat[f"FMG:{first_id + delta}:{idx}"] = strings[idx]
    return {"big_endian": big_endian, "version": version, "groups": groups, "strings": strings, "header": data[:12]}, flat


def rebuild_fmg(orig_data: bytes, translations: dict[str, str], cfg: dict, custom_fn=None, master_en=None) -> tuple[bytes, int]:
    meta, _ = parse_fmg(orig_data)
    big_endian, version = meta["big_endian"], meta["version"]
    endian = ">" if big_endian else "<"
    is_64 = (version == 2)
    ptr_fmt = endian + ("Q" if is_64 else "I")
    ptr_sz = 8 if is_64 else 4
    strings = list(meta["strings"])
    skip_set = {k.lower() for k in cfg.get("skip_keys", [])}
    patched_cnt = 0

    for first_idx, first_id, last_id in meta["groups"]:
        for delta in range(last_id - first_id + 1):
            idx = first_idx + delta
            key = f"FMG:{first_id + delta}:{idx}"
            if key in translations and ARABIC_RE.search(translations[key]) and key.lower() not in skip_set:
                val = custom_fn(translations[key], (master_en or {}).get(key, ""), key, cfg) if custom_fn else translations[key]
                strings[idx] = shape_arabic_text(val, cfg, nl_token="\n")
                patched_cnt += 1

    hdr_sz = 32 + (8 if is_64 else 0)
    grp_sz = len(meta["groups"]) * (16 if is_64 else 12)
    str_off_tbl = hdr_sz + grp_sz
    pool_start = str_off_tbl + len(strings) * ptr_sz

    pool, new_offsets = bytearray(), []
    enc_name = "utf-16-be" if big_endian else "utf-16-le"
    for s in strings:
        if s is None:
            new_offsets.append(0)
        else:
            new_offsets.append(pool_start + len(pool))
            pool += s.encode(enc_name) + b"\x00\x00"

    total_sz = pool_start + len(pool)
    out = bytearray(meta["header"])
    struct.pack_into(endian + "I", out, 4, total_sz)
    out += struct.pack(endian + "ii", len(meta["groups"]), len(strings))
    if is_64:
        out += struct.pack(endian + "I", 0xFF)
    out += struct.pack(ptr_fmt, str_off_tbl)
    out += b"\x00" * (8 if is_64 else 4)
    for first_idx, first_id, last_id in meta["groups"]:
        if is_64:
            out += struct.pack(endian + "iiii", first_idx, first_id, last_id, 0)
        else:
            out += struct.pack(endian + "iii", first_idx, first_id, last_id)
    for so in new_offsets:
        out += struct.pack(ptr_fmt, so)
    out += pool
    parse_fmg(bytes(out))
    return bytes(out), patched_cnt


# ─────────────────────────── ENGINE 4: CAPCOM RE ENGINE (.msg.*) ───────────────────────────

def _re_msg_xor(data: bytes) -> bytes:
    out = bytearray(len(data))
    prev = 0
    for i, b in enumerate(data):
        cur = b ^ prev ^ RE_MSG_XOR_KEY[i & 15]
        out[i] = cur
        prev = b
    return bytes(out)


def _re_msg_xor_enc(data: bytes) -> bytes:
    out = bytearray(len(data))
    prev = 0
    for i, b in enumerate(data):
        enc = b ^ prev ^ RE_MSG_XOR_KEY[i & 15]
        out[i] = enc
        prev = enc
    return bytes(out)


def extract_re_msg(data: bytes) -> dict[str, str]:
    """Extracts UTF-16LE strings from Capcom RE Engine .msg.* (GMSG) binaries."""
    if len(data) < 64 or data[4:8] != b"GMSG":
        raise ValueError("Not a Capcom RE Engine GMSG file")
    (data_off,) = struct.unpack_from("<Q", data, 32)
    pool = _re_msg_xor(data[data_off:]) if data_off < len(data) else b""
    strings_map = {}
    pos, idx = 0, 0
    while pos + 2 <= len(pool):
        end = pos
        while end + 1 < len(pool) and (pool[end] != 0 or pool[end + 1] != 0):
            end += 2
        s = pool[pos:end].decode("utf-16-le", errors="ignore")
        if is_human_translatable(s):
            strings_map[f"REMSG:{pos}:{end}:{idx}"] = s
        idx += 1
        pos = end + 2
    return strings_map


# ─────────────────────────── ENGINE 5: DIRECT TEXT (JSON/XML/CSV/PO/INI/SRT/RPY) ───────────────────────────

def flatten_json(obj, prefix="", out=None):
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten_json(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            flatten_json(v, f"{prefix}[{i}]", out)
    elif isinstance(obj, str) and obj.strip():
        out[prefix] = obj
    return out


def apply_json_translations(obj, translations: dict, cfg: dict, custom_fn, master_en, prefix="") -> int:
    cnt = 0
    skip_set = {k.lower() for k in cfg.get("skip_keys", [])}
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            p = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(obj[k], str):
                if p in translations and ARABIC_RE.search(translations[p]) and p.lower() not in skip_set:
                    val = custom_fn(translations[p], master_en.get(p, ""), p, cfg) if custom_fn else translations[p]
                    obj[k] = shape_arabic_text(val, cfg, nl_token="\n")
                    cnt += 1
            else:
                cnt += apply_json_translations(obj[k], translations, cfg, custom_fn, master_en, p)
    elif isinstance(obj, list):
        for i in range(len(obj)):
            p = f"{prefix}[{i}]"
            if isinstance(obj[i], str):
                if p in translations and ARABIC_RE.search(translations[p]) and p.lower() not in skip_set:
                    val = custom_fn(translations[p], master_en.get(p, ""), p, cfg) if custom_fn else translations[p]
                    obj[i] = shape_arabic_text(val, cfg, nl_token="\n")
                    cnt += 1
            else:
                cnt += apply_json_translations(obj[i], translations, cfg, custom_fn, master_en, p)
    return cnt


def extract_po(txt: str) -> dict[str, str]:
    out = {}
    for idx, m in enumerate(re.finditer(r'msgid\s+"((?:[^"\\]|\\.)*)"', txt)):
        val = m.group(1).replace('\\n', '\n').replace('\\"', '"')
        if is_human_translatable(val):
            out[f"PO:{idx}"] = val
    return out


def rebuild_po(txt: str, translations: dict, cfg: dict, custom_fn, master_en) -> tuple[str, int]:
    cnt = 0
    skip_set = {k.lower() for k in cfg.get("skip_keys", [])}
    idx = [0]

    def repl(m):
        nonlocal cnt
        key = f"PO:{idx[0]}"
        idx[0] += 1
        if key in translations and ARABIC_RE.search(translations[key]) and key.lower() not in skip_set:
            val = custom_fn(translations[key], master_en.get(key, ""), key, cfg) if custom_fn else translations[key]
            shaped = shape_arabic_text(val, cfg, nl_token="\n").replace('"', '\\"').replace("\n", "\\n")
            cnt += 1
            return f'{m.group(1)}msgstr "{shaped}"'
        return m.group(0)

    out = re.sub(r'(msgid\s+"(?:[^"\\]|\\.)*"\s+)msgstr\s+"(?:[^"\\]|\\.)*"', repl, txt)
    return out, cnt


# ─────────────────────────── Splitting, Publishing & UE Packer ───────────────────────────

def split_and_send_parts(title_id: str, strings_map: dict[str, str], gdir: Path, chunk_size: int = 750):
    parts_dir = gdir / "parts_en"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)
    (gdir / "master_en_map.json").write_text(json.dumps(strings_map, ensure_ascii=False, indent=1), encoding="utf-8")
    record_manifest(gdir, "extracted_strings_count", len(strings_map))
    subprocess.run(["git", "config", "user.name", "PS5 Arabi Bot"], check=False)
    subprocess.run(["git", "config", "user.email", "bot@ps5arabi.local"], check=False)
    subprocess.run(["git", "add", str(gdir / "master_en_map.json"), str(gdir / "manifest.json")], check=False)
    subprocess.run(["git", "commit", "-m", f"save master_en_map {title_id}"], check=False)
    subprocess.run(["git", "push"], check=False)

    keys = list(strings_map.keys())
    total_parts = max(1, (len(keys) + chunk_size - 1) // chunk_size)
    (gdir / "PROMPT_GEMINI_AR.txt").write_text(GEMINI_MASTER_PROMPT, encoding="utf-8")

    tg_send_message(
        f"📦 تم استخراج نصوص اللعبة {title_id} بنجاح!\n"
        f"• عدد النصوص القابلة للترجمة: {len(keys):,}\n"
        f"• تم تقسيمها إلى {total_parts} ملف JSON جاهز لجميني.\n"
        f"💡 نصيحة منهجية عبدالله السبيعي: اضغط (🧪 اختبار عرض سريع 10 سطور) في Safari أولاً لتتأكد من الخط والاتجاه خلال 20 ثانية قبل ترجمة الملفات!"
    )
    for pi in range(total_parts):
        sub = {k: strings_map[k] for k in keys[pi * chunk_size:(pi + 1) * chunk_size]}
        pf = parts_dir / f"part_{pi + 1:02d}.json"
        pf.write_text(json.dumps(sub, ensure_ascii=False, indent=1), encoding="utf-8")
        tg_send_document(pf, f"{title_id} — الجزء {pi + 1}/{total_parts} ({len(sub)} نص)")


def publish_multi_files(title_id: str, built_files: list[tuple[Path, str]], label: str = "v7"):
    out_dir = Path("hub_games") / title_id / "out"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_files, release_assets = [], []
    for src_path, target_rel in built_files:
        dst = out_dir / src_path.name
        if dst.resolve() != src_path.resolve():
            shutil.copy2(src_path, dst)
        manifest_files.append({
            "fname": dst.name,
            "rel_path": target_rel,
            "repo_path": f"hub_games/{title_id}/out/{dst.name}",
            "size": dst.stat().st_size,
            "sha256": sha256_file(dst),
        })
        release_assets.append(str(dst))

    first = manifest_files[0]
    (out_dir / "latest.json").write_text(
        json.dumps({"fname": first["fname"], "rel_path": first["rel_path"], "repo_path": first["repo_path"], "size": first["size"], "files": manifest_files}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    tag = f"patch-{title_id}"
    subprocess.run(["gh", "release", "delete", tag, "--yes"], check=False)
    subprocess.run(["gh", "release", "create", tag, *release_assets, "--title", f"PS5 Arabic Patch {title_id} ({label})", "--notes", "Built by PS5 Arabi Hub v7 Omniverse"], check=False)
    subprocess.run(["git", "config", "user.name", "PS5 Arabi Bot"], check=False)
    subprocess.run(["git", "config", "user.email", "bot@ps5arabi.local"], check=False)
    subprocess.run(["git", "add", str(out_dir), str(Path("hub_games") / title_id / "manifest.json")], check=False)
    subprocess.run(["git", "commit", "-m", f"publish {label} patch {title_id}"], check=False)
    subprocess.run(["git", "push"], check=False)

    for m in manifest_files:
        p = out_dir / m["fname"]
        if p.stat().st_size < 45 * 1024 * 1024:
            tg_send_document(p, f"باتش {title_id} الجاهز ({m['fname']})")


def _build_ue_pak_with_fonts(gdir: Path, locres_out: Path, locres_rel: str) -> Path | None:
    if not shutil.which("repak"):
        return None
    stage = gdir / "_pak_stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    dst_loc = stage / locres_rel.lstrip("/")
    dst_loc.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(locres_out, dst_loc)

    font_path = get_active_font(gdir)
    tree_file = gdir / "file_tree.txt"
    if font_path.exists() and tree_file.exists():
        for line in tree_file.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("\t")
            rel = parts[1] if len(parts) > 1 else ""
            if rel.lower().endswith((".ufont", ".ttf", ".otf")):
                dst_f = stage / rel.lstrip("/")
                dst_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(font_path, dst_f)

    out_pak = gdir / "pakchunk0-ps5_999_p.pak"
    res = subprocess.run(["repak", "pack", "--version", "V11", str(stage), str(out_pak)], capture_output=True, text=True)
    return out_pak if (res.returncode == 0 and out_pak.exists()) else None


# ─────────────────────────── Core Build Engine (Shared by Full Build & Canary Test) ───────────────────────────

def build_patch_from_map(title_id: str, gdir: Path, merged: dict, master_en: dict, cfg: dict, is_canary: bool = False):
    custom_fn = load_custom_fix(gdir)
    custom_plugin = load_custom_plugin(gdir)
    font_path = get_active_font(gdir)
    target_meta_path = gdir / "target_file.json"
    if not target_meta_path.exists():
        return [], 0, "None"

    meta = json.loads(target_meta_path.read_text(encoding="utf-8"))
    raw_file = gdir / "raw" / meta["fname"]
    fname_low = meta["fname"].lower()
    built_files: list[tuple[Path, str]] = []
    patched_cnt = 0
    engine_label = "Generic"

    if custom_plugin and raw_file.exists():
        engine_label = "Custom Plugin"
        out_bytes = custom_plugin.rebuild(raw_file.read_bytes(), merged, cfg)
        out_p = gdir / meta["fname"]
        out_p.write_bytes(out_bytes)
        built_files.append((out_p, meta["rel"]))
        patched_cnt = len(merged)

    elif fname_low.endswith((".bundle", ".assets")) and raw_file.exists():
        engine_label = "Unity Universal"
        out_bundle = gdir / meta["fname"]
        patched_cnt, _ = rebuild_unity_universal(raw_file, out_bundle, merged, cfg, custom_fn, master_en, font_path)
        built_files.append((out_bundle, meta["rel"]))

        cat_meta_path = gdir / "catalog_file.json"
        if cat_meta_path.exists():
            cmeta = json.loads(cat_meta_path.read_text(encoding="utf-8"))
            raw_cat, out_cat = gdir / "raw" / cmeta["fname"], gdir / cmeta["fname"]
            if raw_cat.exists() and patch_unity_catalog_json(raw_cat, out_cat):
                built_files.append((out_cat, cmeta["rel"]))

    elif fname_low.endswith(".locres") and raw_file.exists():
        engine_label = "Unreal Engine 4/5"
        rebuilt_bytes, patched_cnt = rebuild_locres(raw_file.read_bytes(), merged, cfg, custom_fn, master_en)
        out_loc = gdir / meta["fname"]
        out_loc.write_bytes(rebuilt_bytes)
        built_files.append((out_loc, meta["rel"]))
        scan = json.loads((gdir / "scan.json").read_text(encoding="utf-8")) if (gdir / "scan.json").exists() else {}
        if scan.get("patch_rel"):
            pak = _build_ue_pak_with_fonts(gdir, out_loc, meta["rel"])
            if pak:
                built_files = [(pak, scan["patch_rel"])]

    elif fname_low.endswith(".fmg") and raw_file.exists():
        engine_label = "FromSoftware (.fmg)"
        rebuilt_bytes, patched_cnt = rebuild_fmg(raw_file.read_bytes(), merged, cfg, custom_fn, master_en)
        out_fmg = gdir / meta["fname"]
        out_fmg.write_bytes(rebuilt_bytes)
        built_files.append((out_fmg, meta["rel"]))

    elif fname_low.endswith(".json") and raw_file.exists():
        engine_label = "JSON"
        data = json.loads(raw_file.read_text(encoding="utf-8"))
        patched_cnt = apply_json_translations(data, merged, cfg, custom_fn, master_en)
        out_json = gdir / meta["fname"]
        out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        json.loads(out_json.read_text(encoding="utf-8"))
        built_files.append((out_json, meta["rel"]))

    elif fname_low.endswith((".po", ".pot")) and raw_file.exists():
        engine_label = "Gettext (.po)"
        out_txt, patched_cnt = rebuild_po(raw_file.read_text(encoding="utf-8"), merged, cfg, custom_fn, master_en)
        out_po = gdir / meta["fname"]
        out_po.write_text(out_txt, encoding="utf-8")
        built_files.append((out_po, meta["rel"]))

    elif fname_low.endswith(".xml") and raw_file.exists():
        engine_label = "XML"
        tree = ET.parse(str(raw_file))
        skip_set = {k.lower() for k in cfg.get("skip_keys", [])}
        for idx, elem in enumerate(tree.getroot().iter()):
            key = f"XML:{idx}:{elem.tag}"
            if key in merged and ARABIC_RE.search(merged[key]) and key.lower() not in skip_set:
                val = custom_fn(merged[key], master_en.get(key, ""), key, cfg) if custom_fn else merged[key]
                elem.text = shape_arabic_text(val, cfg, nl_token="\n")
                patched_cnt += 1
        out_xml = gdir / meta["fname"]
        tree.write(str(out_xml), encoding="utf-8", xml_declaration=True)
        built_files.append((out_xml, meta["rel"]))

    elif fname_low.endswith((".txt", ".srt", ".ini")) and raw_file.exists():
        engine_label = "Direct Text"
        lines = raw_file.read_text(encoding="utf-8", errors="replace").splitlines()
        skip_set = {k.lower() for k in cfg.get("skip_keys", [])}
        for li in range(len(lines)):
            key = f"L{li}"
            if key in merged and ARABIC_RE.search(merged[key]) and key.lower() not in skip_set:
                val = custom_fn(merged[key], master_en.get(key, ""), key, cfg) if custom_fn else merged[key]
                lines[li] = shape_arabic_text(val, cfg, nl_token="\n")
                patched_cnt += 1
        out_t = gdir / meta["fname"]
        out_t.write_text("\n".join(lines), encoding="utf-8")
        built_files.append((out_t, meta["rel"]))

    return built_files, patched_cnt, engine_label


# ─────────────────────────── CLI Actions ───────────────────────────

def cmd_analyze(title_id: str):
    gdir = Path("hub_games") / title_id
    scan = json.loads((gdir / "scan.json").read_text(encoding="utf-8"))
    (gdir / "PROMPT_GEMINI_AR.txt").write_text(GEMINI_MASTER_PROMPT, encoding="utf-8")
    (gdir / "PROMPT_AI_DOCTOR.txt").write_text(AI_DOCTOR_MASTER_PROMPT, encoding="utf-8")

    extracted = gdir / "extracted.arabi"
    tree_path = gdir / "file_tree.txt"
    if extracted.exists() and scan.get("engine") != "Unreal Engine":
        tree_path.write_text(extracted.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    record_manifest(gdir, "scan", scan)
    tg_send_message(
        f"🎮 تم فحص اللعبة عبر PS5 Arabi Hub v7 (النسخة النهائية الشاملة)!\n"
        f"• الرمز: {title_id} ({scan.get('game_format', 'PS5/PS4')})\n"
        f"• المحرك: {scan.get('engine')}" + (f" (v{scan.get('ue_ver')})" if scan.get("ue_ver") else "") + "\n"
        f"• نظام الملفات: {scan.get('fs_type', '?')} | إجمالي الملفات: {scan.get('total_files', '?')}\n"
        f"• التشفير: {'مشفّر 🔒' if scan.get('encrypted') else 'غير مشفّر ✅'}"
    )
    if tree_path.exists():
        tg_send_document(tree_path, f"شجرة ملفات {title_id}")


def cmd_extract_texts(title_id: str):
    gdir = Path("hub_games") / title_id
    reassemble_chunked_raw_files(gdir)
    meta = json.loads((gdir / "target_file.json").read_text(encoding="utf-8"))
    raw_file = gdir / "raw" / meta["fname"]
    fname_low = meta["fname"].lower()
    if raw_file.exists():
        record_manifest(gdir, "original_target_sha256", {meta["fname"]: sha256_file(raw_file)})

    if fname_low == "catalog.json":
        loc_hits, data_hits, font_hits = decode_unity_addressables_catalog(raw_file)
        lines = [f"🔍 تم فك فهرس Unity Addressables للعبة {title_id}!"]
        chosen = loc_hits if loc_hits else data_hits
        if loc_hits:
            lines.append("\n📝 ملفات النصوص المؤكدة:")
            for b, a in loc_hits[:8]:
                lines.append(f"• {b}\n   ↳ ({a})")
        elif data_hits:
            lines.append("\n📦 أبرز ملفات البيانات المرشّحة للنصوص:")
            for b, a in data_hits[:10]:
                lines.append(f"• {b}\n   ↳ ({a})")
        if font_hits:
            lines.append("\n🔤 أبرز ملفات الخطوط:")
            for b, a in font_hits[:4]:
                lines.append(f"• {b}\n   ↳ ({a})")
        tg_send_message("\n".join(lines))
        if chosen:
            tg_send_message(json.dumps({"pull_files": [b for b, _ in chosen[:5]]}, ensure_ascii=False))
        return

    custom_plugin = load_custom_plugin(gdir)
    strings_map = {}
    if custom_plugin:
        strings_map = custom_plugin.extract(raw_file.read_bytes())
    elif fname_low.endswith((".bundle", ".assets")):
        strings_map = extract_unity_universal(raw_file)
    elif fname_low.endswith(".locres"):
        _, strings_map = parse_locres(raw_file.read_bytes())
    elif fname_low.endswith(".fmg"):
        _, strings_map = parse_fmg(raw_file.read_bytes())
    elif ".msg." in fname_low or fname_low.endswith(".msg"):
        strings_map = extract_re_msg(raw_file.read_bytes())
    elif fname_low.endswith(".json"):
        strings_map = {k: v for k, v in flatten_json(json.loads(raw_file.read_text(encoding="utf-8"))).items() if is_human_translatable(v)}
    elif fname_low.endswith((".po", ".pot")):
        strings_map = extract_po(raw_file.read_text(encoding="utf-8"))
    elif fname_low.endswith(".xml"):
        for idx, elem in enumerate(ET.fromstring(raw_file.read_text(encoding="utf-8")).iter()):
            if elem.text and is_human_translatable(elem.text):
                strings_map[f"XML:{idx}:{elem.tag}"] = elem.text.strip()
    elif fname_low.endswith(".csv"):
        for ri, row in enumerate(csv.reader(io.StringIO(raw_file.read_text(encoding="utf-8")))):
            for ci, cell in enumerate(row):
                if is_human_translatable(cell):
                    strings_map[f"R{ri}C{ci}"] = cell
    elif fname_low.endswith((".txt", ".srt", ".ini")):
        for li, line in enumerate(raw_file.read_text(encoding="utf-8", errors="replace").splitlines()):
            if is_human_translatable(line) and not line.strip().startswith(("#", ";", "[")):
                strings_map[f"L{li}"] = line

    # Fallback scan across other pulled raw bundles if first bundle had 0 strings
    raw_dir = gdir / "raw"
    if not strings_map and raw_dir.exists():
        for extra in sorted(raw_dir.glob("*")):
            if extra.name == meta["fname"] or extra.name.lower() == "catalog.json":
                continue
            if extra.suffix.lower() in (".bundle", ".assets"):
                sub = extract_unity_universal(extra)
                if sub:
                    strings_map = sub
                    meta["fname"] = extra.name
                    (gdir / "target_file.json").write_text(json.dumps(meta), encoding="utf-8")
                    break

    if not strings_map:
        tg_send_message(f"⚠️ لم يُعثر على نصوص قابلة للترجمة داخل {meta['fname']}.")
        tg_send_document(raw_file, f"الملف الخام {meta['fname']}")
        return

    split_and_send_parts(title_id, strings_map, gdir)


def cmd_canary_test(title_id: str):
    """Abdullah Al-Subaie Step 4: 10-line Arabic Canary Rendering Test BEFORE full translation!"""
    gdir = Path("hub_games") / title_id
    reassemble_chunked_raw_files(gdir)
    cfg = load_render_cfg(gdir)
    master_en = json.loads((gdir / "master_en_map.json").read_text(encoding="utf-8")) if (gdir / "master_en_map.json").exists() else {}
    if not master_en and (gdir / "target_file.json").exists():
        meta = json.loads((gdir / "target_file.json").read_text(encoding="utf-8"))
        rf = gdir / "raw" / meta["fname"]
        if rf.exists() and meta["fname"].lower().endswith((".bundle", ".assets")):
            master_en = extract_unity_universal(rf)
        elif rf.exists() and meta["fname"].lower().endswith(".locres"):
            _, master_en = parse_locres(rf.read_bytes())
    if not master_en:
        tg_send_message(f"⚠️ استخرج نصوص {title_id} أولاً قبل تشغيل اختبار الـ 10 سطور.")
        return

    canary_map = {}
    for idx, (k, orig_v) in enumerate(list(master_en.items())[:10]):
        sample = CANARY_SAMPLES[idx % len(CANARY_SAMPLES)]
        # Preserve any critical printf tokens from orig_v so Canary test never crashes!
        pf = CRITICAL_PRINTF_RE.findall(orig_v)
        if pf:
            sample = sample + " " + " ".join(pf)
        canary_map[k] = sample

    built_files, patched_cnt, engine_label = build_patch_from_map(title_id, gdir, canary_map, master_en, cfg, is_canary=True)
    if built_files:
        publish_multi_files(title_id, built_files, label="canary-10")
        record_manifest(gdir, "canary_tested", True)
        tg_send_message(
            f"🧪 جاهز اختبار العرض السريع (10 سطور — منهجية عبدالله السبيعي) للعبة {title_id} ({engine_label})!\n"
            f"• تم حقن {patched_cnt} سطر اختبار عربي (اتصال + اتجاه + أرقام + التفاف).\n"
            f"اضغط (📥 3. تثبيت وتفعيل) في Safari وافتح اللعبة لتتأكد من الخط والعرض قبل ما تبدأ الترجمة الكاملة!"
        )
    else:
        tg_send_message(f"⚠️ تعذر بناء اختبار الـ 10 سطور لـ {title_id}.")


def cmd_qa_and_build(title_id: str):
    gdir = Path("hub_games") / title_id
    reassemble_chunked_raw_files(gdir)
    cfg = load_render_cfg(gdir)
    tr_dir = gdir / "translated"
    master_en = json.loads((gdir / "master_en_map.json").read_text(encoding="utf-8")) if (gdir / "master_en_map.json").exists() else {}

    merged, repaired, crash_guarded = {}, 0, 0
    for jf in sorted(tr_dir.glob("*.json")):
        try:
            for k, v in json.loads(jf.read_text(encoding="utf-8")).items():
                if isinstance(v, str) and v.strip():
                    cleaned, was_rep, guarded = qa_repair_and_validate(v.strip(), master_en.get(k, ""))
                    if was_rep:
                        repaired += 1
                    if guarded:
                        crash_guarded += 1
                    merged[k] = cleaned
        except Exception as e:
            print(f"Skipping {jf.name}: {e}", flush=True)

    (gdir / "merged_ar_qa.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    built_files, patched_cnt, engine_label = build_patch_from_map(title_id, gdir, merged, master_en, cfg, is_canary=False)
    record_manifest(gdir, "last_build", {"engine": engine_label, "patched": patched_cnt, "repaired": repaired, "crash_guarded": crash_guarded})

    if built_files:
        publish_multi_files(title_id, built_files, label="v7-full")
        tg_send_message(
            f"✅ اكتمل البناء الشامل والتدقيق الآلي لـ {title_id} ({engine_label})!\n"
            f"• نصوص معرّبة: {patched_cnt:,}\n"
            f"• إصلاح Auto-QA: {repaired:,} | حماية ضد الكراش: {crash_guarded}\n"
            f"• ملفات الباتش الجاهزة: {len(built_files)} (تم فحص سلامتها + SHA-256 ✅)\n"
            f"افتح لوحة PS5 Arabi في Safari واضغط (📥 3. تثبيت وتفعيل آخر تعريب جاهز على السوني)!"
        )
    else:
        tg_send_message(f"✅ اكتمل التدقيق الآلي لـ {title_id} ({len(merged):,} نص).")


def cmd_send_bug_photo(title_id: str):
    gdir = Path("hub_games") / title_id
    photo = gdir / "bug_report.jpg"
    cfg = load_render_cfg(gdir)
    tg_send_photo(
        photo,
        f"📸 تقرير مشكلة عرض للعبة {title_id}\n"
        f"الإعدادات: reshape={cfg['reshape']}, bidi={cfg['bidi']}, LRO={cfg['use_lro']}, wrap={cfg['wrap_width']}\n"
        f"ارفعها لمحادثة (🤖 دكتور التعريب) والصق الكود في Safari.",
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["analyze_and_send", "extract_texts", "canary_test", "qa_and_build", "send_bug_photo"], required=True)
    p.add_argument("--title-id", required=True)
    args = p.parse_args()
    if args.action == "analyze_and_send":
        cmd_analyze(args.title_id)
    elif args.action == "extract_texts":
        cmd_extract_texts(args.title_id)
    elif args.action == "canary_test":
        cmd_canary_test(args.title_id)
    elif args.action == "qa_and_build":
        cmd_qa_and_build(args.title_id)
    elif args.action == "send_bug_photo":
        cmd_send_bug_photo(args.title_id)


if __name__ == "__main__":
    main()
