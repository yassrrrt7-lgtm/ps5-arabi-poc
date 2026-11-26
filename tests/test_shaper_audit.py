"""
Unit tests verifying the 3 bug fixes in safe_arabic_shaper_fixed.py.
Runs cleanly even without arabic_reshaper installed (tests regex, token count > 27, visible_length).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud_worker" / "toolkit"))
import safe_arabic_shaper_fixed as shaper


def test_unlimited_tokens_above_27():
    line = " ".join(f"{{v{i}}}" for i in range(40))
    matches = shaper.TOKEN_RE.findall(line)
    assert len(matches) == 40, f"Expected 40 tokens, got {len(matches)}"
    assert shaper._sentinel(39) == "\u200F" + chr(0xE000 + 39) + "\u200F"


def test_printf_and_button_protection():
    sample = "Score: %d pts (%1$s) [BTN_X] <color=#FF0000>{player}</color> $1"
    matches = shaper.TOKEN_RE.findall(sample)
    for expected in ["%d", "%1$s", "[BTN_X]", "<color=#FF0000>", "{player}", "</color>", "$1"]:
        assert expected in matches, f"Missing protected token: {expected}"


def test_visible_length_ignores_tags():
    raw = "<color=#FF0000>مرحبا</color>"
    assert shaper.visible_length(raw) == 5, f"Expected 5, got {shaper.visible_length(raw)}"


if __name__ == "__main__":
    test_unlimited_tokens_above_27()
    test_printf_and_button_protection()
    test_visible_length_ignores_tags()
    print("ALL AUDIT UNIT TESTS PASSED")
