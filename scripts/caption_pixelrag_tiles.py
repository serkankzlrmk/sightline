#!/usr/bin/env python3
"""Classify PixelRAG tiles with an OpenRouter vision model.

This is intentionally opt-in: it sends images to the configured model and may
incur API costs. Use --limit for a controlled batch.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

PROMPT = """Classify this humanitarian report page tile. Return JSON only with:
visual_type: one of chart, map, table, diagram, infographic, scanned_document, evidence_photo, decorative
caption: concise factual description of meaningful content
relevance: number from 0 to 1 for humanitarian information retrieval
is_decorative: boolean

If this is a logo, stock photo, cover decoration, background, or layout-only page,
use visual_type=decorative, is_decorative=true, relevance <= 0.2."""


def classify(image: Path, model: str, base_url: str, api_key: str) -> dict:
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                    ],
                }
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tiles_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=os.getenv("VISION_MODEL", "google/gemini-2.5-flash"))
    parser.add_argument("--base-url", default=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is required; no request was sent")
    images = sorted(args.tiles_dir.glob("**/tile_*.jpg"))[: args.limit]
    results = {}
    for image in images:
        tile_index = image.stem.rsplit("_", 1)[-1]
        result = classify(image, args.model, args.base_url, api_key)
        results[tile_index] = result
        print(f"classified tile {tile_index}: {result.get('visual_type')}")
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"tiles": len(results), "output": str(args.output)}))


if __name__ == "__main__":
    main()
