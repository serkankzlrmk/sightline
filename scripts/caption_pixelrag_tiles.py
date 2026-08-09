#!/usr/bin/env python3
"""Classify PixelRAG tiles with an OpenRouter vision model.

This is intentionally opt-in: it sends images to the configured model and may
incur API costs. Use --limit for a controlled batch.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

PROMPT = """Classify this humanitarian report page tile. Return JSON only with:
visual_type: one of chart, map, table, diagram, infographic, scanned_document, evidence_photo, decorative
caption: concise factual description of meaningful content
relevance: number from 0 to 1 for humanitarian information retrieval
is_decorative: boolean

If this is a logo, stock photo, cover decoration, background, or layout-only page,
use visual_type=decorative, is_decorative=true, relevance <= 0.2."""


def parse_result(content: str) -> dict:
    content = content.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "visual_type": "unknown",
            "caption": "Visual tile could not be classified reliably.",
            "relevance": 0.0,
            "is_decorative": True,
        }


def image_base64(image: Path, max_size: int) -> str:
    with Image.open(image) as source:
        source = source.convert("RGB")
        source.thumbnail((max_size, max_size))
        buffer = io.BytesIO()
        source.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("ascii")


def classify_openrouter(image: Path, model: str, base_url: str, api_key: str, max_size: int) -> dict:
    encoded = image_base64(image, max_size)
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
    return parse_result(content)


def classify_ollama(image: Path, model: str, base_url: str, max_size: int) -> dict:
    encoded = image_base64(image, max_size)
    response = requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [{"role": "user", "content": PROMPT, "images": [encoded]}],
        },
        timeout=180,
    )
    response.raise_for_status()
    return parse_result(response.json()["message"]["content"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tiles_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=("ollama", "openrouter"), default=os.getenv("VISION_PROVIDER", "ollama"))
    parser.add_argument("--model", default=os.getenv("VISION_MODEL", "gemma4:e4b"))
    parser.add_argument("--base-url", default=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    parser.add_argument("--ollama-url", default=os.getenv("LOCAL_OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-size", type=int, default=1600)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if args.provider == "openrouter" and not api_key:
        raise SystemExit("OPENROUTER_API_KEY is required; no request was sent")
    images = sorted(args.tiles_dir.glob("**/tile_*.jpg"))[: args.limit]
    results = json.loads(args.output.read_text(encoding="utf-8")) if args.resume and args.output.exists() else {}
    for image in images:
        tile_index = image.stem.rsplit("_", 1)[-1]
        article_key = image.parent.name.split(".", 1)[0]
        result_key = f"{article_key}:{tile_index}"
        if result_key in results:
            continue
        if args.provider == "ollama":
            result = classify_ollama(image, args.model, args.ollama_url, args.max_size)
        else:
            result = classify_openrouter(image, args.model, args.base_url, api_key, args.max_size)
        results[result_key] = result
        args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"classified article {article_key} tile {tile_index}: {result.get('visual_type')}")
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"tiles": len(results), "output": str(args.output)}))


if __name__ == "__main__":
    main()
