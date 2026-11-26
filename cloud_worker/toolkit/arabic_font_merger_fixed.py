"""
Audit-Hardened Arabic Font Merger (TTF + OTF Detection & Validation)
Fixes KeyError: 'glyf' crash when encountering OpenType CFF (.otf) fonts.
Credit: Based on arabic_font_merger.py by V7dt1 / axxx503 (non-commercial attribution).
"""

import io
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.transformPen import TransformPen


def detect_font_outline_type(font_bytes: bytes) -> str:
    tt = TTFont(io.BytesIO(font_bytes))
    if "glyf" in tt:
        return "truetype"
    if "CFF " in tt or "CFF2" in tt:
        return "opentype_cff"
    return "unknown"


def merge_arabic_into_font(base_font_bytes: bytes, arabic_ttf_path: str, scale_factor: float = 1.15) -> bytes:
    """
    Merges Arabic glyphs into a TrueType (.ttf) game font.
    If the game font is OpenType CFF (.otf), returns the Arabic TTF directly as a safe fallback
    rather than crashing with KeyError('glyf').
    """
    outline_type = detect_font_outline_type(base_font_bytes)
    if outline_type != "truetype":
        with open(arabic_ttf_path, "rb") as f:
            return f.read()

    import arabic_reshaper
    from arabic_reshaper.letters import LETTERS_ARABIC, ISOLATED

    base_tt = TTFont(io.BytesIO(base_font_bytes))
    ar_tt = TTFont(arabic_ttf_path)

    base_upm = base_tt["head"].unitsPerEm
    ar_upm = ar_tt["head"].unitsPerEm
    scale = (base_upm / float(ar_upm)) * scale_factor

    ar_cmap = dict(ar_tt.getBestCmap())
    for base_ch, forms in LETTERS_ARABIC.items():
        base_cp = ord(base_ch)
        if base_cp in ar_cmap and forms[ISOLATED]:
            isol_cp = ord(forms[ISOLATED])
            if isol_cp not in ar_cmap:
                ar_cmap[isol_cp] = ar_cmap[base_cp]

    target_cps = {
        cp: gname
        for cp, gname in ar_cmap.items()
        if (0x0600 <= cp <= 0x06FF) or (0x0750 <= cp <= 0x077F)
        or (0x08A0 <= cp <= 0x08FF) or (0xFB50 <= cp <= 0xFDFF)
        or (0xFE70 <= cp <= 0xFEFF)
    }

    ar_glyph_set = ar_tt.getGlyphSet()
    base_glyf = base_tt["glyf"]
    base_hmtx = base_tt["hmtx"].metrics
    base_glyph_order = list(base_tt.getGlyphOrder())
    base_names = set(base_glyph_order)

    ar_to_base = {}
    for cp, ar_gname in sorted(target_cps.items()):
        if ar_gname not in ar_to_base:
            new_gname = f"ar_{ar_gname}"
            while new_gname in base_names:
                new_gname += "_"
            pen = TTGlyphPen(None)
            tpen = TransformPen(pen, (scale, 0, 0, scale, 0, 0))
            ar_glyph_set[ar_gname].draw(tpen)
            new_glyph = pen.glyph()
            new_glyph.recalcBounds(base_glyf)
            base_glyf[new_gname] = new_glyph
            ar_adv, ar_lsb = ar_tt["hmtx"].metrics[ar_gname]
            new_adv = int(round(ar_adv * scale))
            new_lsb = new_glyph.xMin if hasattr(new_glyph, "xMin") else int(round(ar_lsb * scale))
            base_hmtx[new_gname] = (new_adv, new_lsb)
            base_glyph_order.append(new_gname)
            base_names.add(new_gname)
            ar_to_base[ar_gname] = new_gname

    base_tt.setGlyphOrder(base_glyph_order)
    base_tt["maxp"].numGlyphs = len(base_glyph_order)
    for table in base_tt["cmap"].tables:
        if table.isUnicode():
            for cp, ar_gname in target_cps.items():
                if table.format == 4 and cp > 0xFFFF:
                    continue
                table.cmap[cp] = ar_to_base[ar_gname]

    out = io.BytesIO()
    base_tt.save(out)
    return out.getvalue()
