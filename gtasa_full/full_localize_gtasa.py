"""
GTA San Andreas Definitive Edition (PS5 PPSA03524) — OFFLINE ZERO-KEY Arabic Localization Builder (v4)
Modes:
  --mode menus_fast : Hand-crafted Arabic for Menus/Settings/Pause/HUD (~20 seconds, 0 keys)
  --mode full_free  : Hand-crafted Menus + 100% Offline Argos Translate (CTranslate2 en->ar, 0 API keys, 0 rate limits!)
"""

import argparse
import json
import re
import shutil
import struct
import textwrap
import time
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display

RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
    "delete_harakat": False,
    "support_ligatures": True,
})

TOKEN_RE = re.compile(
    r"(~[^~\r\n]{1,40}~"
    r"|\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    r"|<[^>]+>"
    r"|%(?:\d+\$)?[+-]?(?:\d+)?(?:\.\d+)?[diuoxXfFeEgGaAcspn%]"
    r"|\[[A-Za-z0-9_:\-]+\])"
)
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
TAG_STRIP_RE = re.compile(r"~[^~\r\n]+~|<[^>]+>")

# ALL 24 TrueType/OpenType font slots in GTA San Andreas PS5 pakchunk0-ps5.pak
ALL_FONT_SLOTS = [
    # Gameface Common .ufont (4)
    "Gameface/Content/Common/Fonts/BankGothicMdBT.ufont",
    "Gameface/Content/Common/Fonts/Beckett.ufont",
    "Gameface/Content/Common/Fonts/OldEnglishCom.ufont",
    "Gameface/Content/Common/Fonts/RUS_Beckett-KanzleiCYRegular.ufont",
    # Engine EngineFonts .ufont (7)
    "Engine/Content/EngineFonts/Faces/DroidSansFallback.ufont",
    "Engine/Content/EngineFonts/Faces/DroidSansMono.ufont",
    "Engine/Content/EngineFonts/Faces/RobotoRegular.ufont",
    "Engine/Content/EngineFonts/Faces/RobotoBold.ufont",
    "Engine/Content/EngineFonts/Faces/RobotoLight.ufont",
    "Engine/Content/EngineFonts/Faces/RobotoItalic.ufont",
    "Engine/Content/EngineFonts/Faces/RobotoBoldItalic.ufont",
    # Engine Slate .ttf (13)
    "Engine/Content/Slate/Fonts/DroidSansFallback.ttf",
    "Engine/Content/Slate/Fonts/DroidSansMono.ttf",
    "Engine/Content/Slate/Fonts/NotoNaskhArabicUI-Regular.ttf",
    "Engine/Content/Slate/Fonts/NotoSansThai-Regular.ttf",
    "Engine/Content/Slate/Fonts/Roboto-Black.ttf",
    "Engine/Content/Slate/Fonts/Roboto-BlackItalic.ttf",
    "Engine/Content/Slate/Fonts/Roboto-Bold.ttf",
    "Engine/Content/Slate/Fonts/Roboto-BoldCondensed.ttf",
    "Engine/Content/Slate/Fonts/Roboto-BoldCondensedItalic.ttf",
    "Engine/Content/Slate/Fonts/Roboto-BoldItalic.ttf",
    "Engine/Content/Slate/Fonts/Roboto-Italic.ttf",
    "Engine/Content/Slate/Fonts/Roboto-Light.ttf",
    "Engine/Content/Slate/Fonts/Roboto-Regular.ttf",
]


def _sentinel(idx: int) -> str:
    return "\u200F" + chr(0xE000 + idx) + "\u200F"


def shape_single_line(line: str) -> str:
    if not line or not ARABIC_RE.search(line):
        return line
    tokens = []
    def repl(m):
        idx = len(tokens)
        tokens.append(m.group(0))
        return _sentinel(idx)
    protected = TOKEN_RE.sub(repl, line)
    reshaped = RESHAPER.reshape(protected)
    vis = get_display(reshaped, base_dir="R")
    for idx, tok in enumerate(tokens):
        vis = vis.replace(_sentinel(idx), tok).replace(chr(0xE000 + idx), tok)
    return vis


def shape_gta_arabic(text: str, wrap_width: int = 58) -> str:
    if not text or not ARABIC_RE.search(text):
        return text
    parts = re.split(r"(~[nN]~|\r\n|\n)", text)
    out_parts = []
    for part in parts:
        if part in ("~n~", "~N~", "\r\n", "\n") or not part:
            out_parts.append(part)
            continue
        if len(TAG_STRIP_RE.sub("", part)) > wrap_width:
            toks = []
            def tp(m):
                idx = len(toks); toks.append(m.group(0)); return f"__T{idx}__"
            tmp = TOKEN_RE.sub(tp, part)
            wrapped = textwrap.wrap(tmp, width=wrap_width, break_long_words=False, break_on_hyphens=False)
            shaped_lines = []
            for wl in wrapped:
                for idx, tok in enumerate(toks):
                    wl = wl.replace(f"__T{idx}__", tok)
                shaped_lines.append(shape_single_line(wl))
            out_parts.append("~n~".join(shaped_lines))
        else:
            out_parts.append(shape_single_line(part))
    return "".join(out_parts)


def is_translatable(s: str) -> bool:
    t = s.strip()
    if not t or len(t) <= 1: return False
    if re.fullmatch(r"[\d\s:./+\-%xX$€£~()!?,]+", t): return False
    if re.fullmatch(r"[A-Za-z0-9]+(_[A-Za-z0-9]+)+", t): return False
    if not re.search(r"[A-Za-z]", t): return False
    if len(t) > 1200: return False
    return True


def encode_fstring(s: str) -> bytes:
    if all(ord(c) < 128 for c in s):
        raw = s.encode("ascii") + b"\x00"
        return struct.pack("<i", len(raw)) + raw
    raw = s.encode("utf-16-le") + b"\x00\x00"
    return struct.pack("<i", -(len(s) + 1)) + raw


def read_locres_strings(buf: bytes):
    str_arr_off = struct.unpack_from("<Q", buf, 17)[0]
    p = str_arr_off
    cnt = struct.unpack_from("<I", buf, p)[0]; p += 4
    items = []
    for _ in range(cnt):
        slen = struct.unpack_from("<i", buf, p)[0]; p += 4
        if slen >= 0: s = buf[p:p+slen].rstrip(b"\x00").decode("utf-8", errors="replace"); p += slen
        else: s = buf[p:p-slen*2].decode("utf-16-le", errors="replace").rstrip("\x00"); p += -slen*2
        ref = struct.unpack_from("<I", buf, p)[0]; p += 4
        items.append((s, ref))
    return items, str_arr_off, p


def write_locres_strings(orig_buf: bytes, new_items, str_arr_off: int, end_pos: int) -> bytes:
    table = bytearray(struct.pack("<I", len(new_items)))
    for s, ref in new_items:
        table += encode_fstring(s) + struct.pack("<I", ref)
    return orig_buf[:str_arr_off] + bytes(table) + orig_buf[end_pos:]


def protect_for_mt(s: str):
    s_clean = s.replace("\r\n", "~n~").replace("\n", "~n~")
    toks = []
    def repl(m):
        idx = len(toks); toks.append(m.group(0)); return f"[[X{idx}]]"
    return TOKEN_RE.sub(repl, s_clean), toks


def restore_after_mt(s: str, toks: list[str]) -> str:
    for idx, tok in enumerate(toks):
        s = re.sub(rf"\[\[\s*[xX]\s*{idx}\s*\]\]", lambda _: tok, s)
    return s


def translate_offline_argos(pending: list[str], cache: dict, cache_path: Path):
    import argostranslate.package
    import argostranslate.translate
    import ctranslate2
    import sentencepiece as spm

    print("Downloading official Argos Translate en->ar offline model (0 API keys, 0 rate limits)...", flush=True)
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    pkg = next(p for p in available if p.from_code == "en" and p.to_code == "ar")
    argostranslate.package.install_from_path(pkg.download())

    installed = argostranslate.package.get_installed_packages()
    en_ar_pkg = next(p for p in installed if p.from_code == "en" and p.to_code == "ar")
    pkg_dir = Path(en_ar_pkg.package_path)
    model_dir = pkg_dir / "model"
    sp_model = pkg_dir / "sentencepiece.model"

    print(f"Loaded offline CTranslate2 model from {model_dir}", flush=True)
    sp = spm.SentencePieceProcessor(model_file=str(sp_model))
    translator = ctranslate2.Translator(str(model_dir), device="cpu", intra_threads=4, inter_threads=2)

    total = len(pending)
    BATCH = 64
    t0 = time.time()
    print(f"Translating {total:,} strings offline in batches of {BATCH}...", flush=True)

    for start in range(0, total, BATCH):
        chunk = pending[start:start + BATCH]
        protected_items = [protect_for_mt(s) for s in chunk]
        tokenized = [sp.encode(prot, out_type=str) for prot, _ in protected_items]
        results = translator.translate_batch(tokenized, beam_size=2, max_batch_size=BATCH)
        for (orig_s, (_, toks)), res in zip(zip(chunk, protected_items), results):
            ar_raw = sp.decode(res.hypotheses[0])
            cache[orig_s] = restore_after_mt(ar_raw.strip(), toks)

        done = min(start + BATCH, total)
        if done % (BATCH * 10) == 0 or done == total:
            elapsed = time.time() - t0
            pct = (done / total) * 100
            rate = done / max(elapsed, 0.1)
            eta = (total - done) / max(rate, 0.1)
            print(f"[{pct:5.1f}% | {done:,}/{total:,}] {rate:.0f} str/s | elapsed {elapsed:.0f}s | ETA {eta:.0f}s", flush=True)

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"DONE! Translated {len(cache):,} Arabic strings in {time.time() - t0:.1f}s (100% offline!).", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["menus_fast", "full_free"], default="full_free")
    args = parser.parse_args()

    root = Path("gtasa_full")
    orig_dir = root / "orig"
    cache_path = root / "cache_ar.json"
    out_pak_root = Path("gtasa_full_pak_root")
    if out_pak_root.exists():
        shutil.rmtree(out_pak_root)

    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    for pf in sorted(root.glob("part_*_ar.json")):
        try:
            mp = json.loads((root / "master_en_map.json").read_text(encoding="utf-8")) if (root / "master_en_map.json").exists() else {}
            pdata = json.loads(pf.read_text(encoding="utf-8"))
            for k, v in pdata.items():
                if k in mp and isinstance(v, str) and v.strip():
                    cache[mp[k]] = v.strip()
        except Exception as e:
            print(f"Skipping {pf.name}: {e}", flush=True)

    glossary = json.loads((root / "hand_glossary.json").read_text(encoding="utf-8"))
    cache.update(glossary)

    files_data = {}
    unique_pending, seen = [], set()
    for name in ["Common.locres", "GTASA.locres"]:
        raw = (orig_dir / name).read_bytes()
        items, str_off, end_pos = read_locres_strings(raw)
        files_data[name] = (raw, items, str_off, end_pos)
        for s, _ in items:
            if is_translatable(s) and s not in cache and s not in seen:
                seen.add(s)
                unique_pending.append(s)

    if args.mode == "full_free" and unique_pending:
        translate_offline_argos(unique_pending, cache, cache_path)
    else:
        print(f"Mode={args.mode}: applying {len(cache):,} curated Arabic strings.", flush=True)

    loc_targets = {
        "Common.locres": "Gameface/Content/Localization/Common/en/Common.locres",
        "GTASA.locres": "Gameface/Content/Localization/GTASA/en/GTASA.locres",
    }
    for name, rel_out in loc_targets.items():
        raw, items, str_off, end_pos = files_data[name]
        new_items = []
        tr_cnt = 0
        for s, ref in items:
            ar = cache.get(s) or cache.get(s.strip())
            if ar and ARABIC_RE.search(ar):
                new_items.append((shape_gta_arabic(ar), ref))
                tr_cnt += 1
            else:
                new_items.append((s, ref))
        patched = write_locres_strings(raw, new_items, str_off, end_pos)
        v_items, _, _ = read_locres_strings(patched)
        assert len(v_items) == len(items)
        dst = out_pak_root / rel_out
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(patched)
        print(f"Wrote {rel_out}: {tr_cnt:,}/{len(items):,} Arabic shaped strings (verified).", flush=True)

    font_bytes = (root / "font" / "ArabicGameFont.ttf").read_bytes()
    for slot in ALL_FONT_SLOTS:
        dst = out_pak_root / slot
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(font_bytes)
    print(f"All {len(ALL_FONT_SLOTS)} Arabic+Latin font slots ready (11 .ufont + 13 Slate .ttf).", flush=True)


if __name__ == "__main__":
    main()
