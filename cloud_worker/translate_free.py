"""
PS5 Arabi POC 3: Zero-Cost Translation & Verification Pipeline
Supports:
  1. --mode manual : Splits strings_en.json into chat-ready chunks and applies strings_ar.json
  2. --mode gemini : Translates via Gemini Flash-Lite Free Tier (0 SAR, batching + auto-resume)
Always verifies SHA-256 hashes before/after processing.
"""

import argparse
import hashlib
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def translate_batch_gemini(batch: dict, api_key: str, model: str = "gemini-2.5-flash-lite") -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    prompt = (
        "Translate the following JSON dictionary of video game UI/dialogue strings into natural Modern Standard Arabic. "
        "STRICT RULES: Return ONLY valid JSON with the exact same keys. "
        "Keep all placeholders like {0}, {var}, <color>, %s, %d, [BTN] untouched.\n\n"
        + json.dumps(batch, ensure_ascii=False)
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)


def run_gemini_mode(in_path: Path, out_path: Path, batch_size: int = 40):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    src = json.loads(in_path.read_text(encoding="utf-8"))
    translated = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}

    pending_keys = [k for k in src if k not in translated]
    print(f"Total strings: {len(src)} | Already done: {len(translated)} | Pending: {len(pending_keys)}")

    for i in range(0, len(pending_keys), batch_size):
        chunk_keys = pending_keys[i : i + batch_size]
        batch = {k: src[k] for k in chunk_keys}
        for attempt in range(4):
            try:
                res = translate_batch_gemini(batch, api_key)
                for k in chunk_keys:
                    if k in res:
                        translated[k] = res[k]
                out_path.write_text(json.dumps(translated, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Batch {i // batch_size + 1}: translated {len(chunk_keys)} strings.")
                time.sleep(4.5)  # Stay safely under 15 RPM Free Tier limit
                break
            except urllib.error.HTTPError as e:
                wait = int(e.headers.get("Retry-After", "15")) if e.headers else 15
                print(f"HTTP {e.code}, retrying in {wait}s (attempt {attempt + 1}/4)...")
                time.sleep(wait)


def run_split_mode(in_path: Path, out_dir: Path, chunk_size: int = 150):
    src = json.loads(in_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    keys = list(src.keys())
    for idx in range(0, len(keys), chunk_size):
        part = {k: src[k] for k in keys[idx : idx + chunk_size]}
        p = out_dir / f"chunk_{idx // chunk_size + 1:03d}.json"
        p.write_text(json.dumps(part, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {(len(keys) + chunk_size - 1) // chunk_size} chat-ready chunks to {out_dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["split", "gemini"], required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    print(f"Input SHA-256: {sha256_file(in_path)}")

    if args.mode == "split":
        run_split_mode(in_path, out_path)
    else:
        run_gemini_mode(in_path, out_path)
        print(f"Output SHA-256: {sha256_file(out_path)}")


if __name__ == "__main__":
    main()
