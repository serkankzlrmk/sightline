#!/usr/bin/env python3
"""Minimal Google Gemini smoke test (no server, no secrets printed).

Run after setting GOOGLE_API_KEY and LLM_PROVIDER=google:

    LLM_PROVIDER=google python scripts/smoke_google.py
    LLM_PROVIDER=google python scripts/smoke_google.py --model google/gemini-3.8-flash --tool
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.messages import HumanMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

import config  # noqa: E402
from config import _LLM_API_KEY, _LLM_BASE_URL, _LLM_TIMEOUT, CHAT_MODELS, provider_model_name  # noqa: E402


@tool
def get_test_value() -> str:
    """Return the fixed smoke-test value."""
    return "sightline-smoke-ok"


def main() -> int:
    ap = argparse.ArgumentParser(description="Google Gemini connectivity smoke test")
    ap.add_argument("--model", default=CHAT_MODELS["flash"]["model"])
    ap.add_argument("--tool", action="store_true", help="also test one tool call")
    args = ap.parse_args()

    if config.LLM_PROVIDER != "google":
        print(f"LLM_PROVIDER is {config.LLM_PROVIDER!r}; set LLM_PROVIDER=google for this smoke test.")
        return 2
    if not _LLM_API_KEY:
        print("GOOGLE_API_KEY is empty; add it to .env (never commit .env).")
        return 2

    model_id = provider_model_name(args.model, "google")
    llm = ChatOpenAI(
        model=model_id,
        base_url=_LLM_BASE_URL,
        api_key=_LLM_API_KEY,
        temperature=0,
        max_tokens=128,
        timeout=_LLM_TIMEOUT,
    )
    try:
        response = llm.invoke([HumanMessage(content="Reply with exactly: SIGHTLINE_OK")])
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL text call: {type(exc).__name__}")
        return 1
    text = str(response.content or "").strip()
    print(f"provider=google model={model_id}")
    print(f"text_call={text[:120]!r}")
    if args.tool:
        try:
            with_tools = llm.bind_tools([get_test_value])
            tool_response = with_tools.invoke([HumanMessage(content="Call get_test_value and report its result.")])
            calls = getattr(tool_response, "tool_calls", None) or []
            print(f"tool_call={'yes' if calls else 'no'} names={[c.get('name') for c in calls]}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL tool call: {type(exc).__name__}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
