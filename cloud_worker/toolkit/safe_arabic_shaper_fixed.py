"""
Fixed Safe Arabic Reshaper & BiDi Pre-Processor (Audit-Hardened)
Fixes all 3 bugs found in the original shaper:
1. Unlimited protected tokens (uses PUA U+E000..U+F8FF instead of 27-char Hebrew limit).
2. Protects {placeholders}, <tags>, %s/%d/%.2f printf tokens, $1, and [BTN] icons.
3. Measures wrap_width on visible text only (excluding rich-text <tags>).

Credit: Based on safe_arabic_shaper.py by V7dt1 / axxx503 (non-commercial attribution).
"""

import re
import textwrap

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_SHAPING_LIBS = True
    RESHAPER = arabic_reshaper.ArabicReshaper(configuration={
        "delete_harakat": False,
        "support_ligatures": True,
    })
except ImportError:
    HAS_SHAPING_LIBS = False
    RESHAPER = None

# Protects: {var}, {var:plural:a|b}, <tag>, %s, %1$d, %.2f, $1, [ICON]
TOKEN_RE = re.compile(
    r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    r"|<[^>]+>"
    r"|%(?:\d+\$)?[+-]?(?:\d+)?(?:\.\d+)?[diuoxXfFeEgGaAcspn%]"
    r"|\$\d+"
    r"|\[[A-Za-z0-9_:\-]+\])"
)
PLURAL_RE = re.compile(r"^\{([a-zA-Z0-9_]+):plural:([^|{}]+)\|([^{}]+)\}$")
ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
TAG_ONLY_RE = re.compile(r"<[^>]+>")


def _sentinel(idx: int) -> str:
    """Uses Unicode Private Use Area (6,400 slots) wrapped with RLM so BiDi keeps token order."""
    if idx >= 6400:
        raise ValueError("Exceeded 6,400 tokens in a single line")
    return "\u200F" + chr(0xE000 + idx) + "\u200F"


def visible_length(text: str) -> int:
    return len(TAG_ONLY_RE.sub("", text))


def shape_token_if_plural(tok: str) -> str:
    m = PLURAL_RE.match(tok)
    if not m:
        return tok
    var_name, c1, c2 = m.group(1), m.group(2), m.group(3)
    return f"{{{var_name}:plural:{shape_line(c1)}|{shape_line(c2)}}}"


def shape_line(line: str) -> str:
    if not line or not ARABIC_RE.search(line):
        return line
    if not HAS_SHAPING_LIBS:
        raise RuntimeError("Install arabic-reshaper and python-bidi before shaping.")

    tokens = []

    def repl(m):
        idx = len(tokens)
        tokens.append(shape_token_if_plural(m.group(0)))
        return _sentinel(idx)

    protected = TOKEN_RE.sub(repl, line)
    reshaped = RESHAPER.reshape(protected)
    vis = get_display(reshaped, base_dir="R")

    for idx, tok in enumerate(tokens):
        vis = vis.replace(_sentinel(idx), tok)
        vis = vis.replace(chr(0xE000 + idx), tok)
    return vis


def shape_arabic_text(logical_text: str, wrap_width: int = 58) -> str:
    if not logical_text or not ARABIC_RE.search(logical_text):
        return logical_text

    out_lines = []
    for raw_line in logical_text.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            out_lines.append("")
            continue

        tokens = []

        def tok_protect(m):
            idx = len(tokens)
            tokens.append(m.group(0))
            return f"__T{idx}__"

        temp = TOKEN_RE.sub(tok_protect, stripped)
        if visible_length(stripped) > wrap_width:
            wrapped = textwrap.wrap(
                temp, width=wrap_width, break_long_words=False, break_on_hyphens=False
            )
        else:
            wrapped = [temp]

        for wline in wrapped:
            for idx, tok in enumerate(tokens):
                wline = wline.replace(f"__T{idx}__", tok)
            out_lines.append(shape_line(wline))

    return "\n".join(out_lines)
