"""Print the pricing key of every model the Models API serves that CTFL cannot price.

Run by .github/workflows/model-watch.yml from the repo root with PYTHONPATH=.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ctfl.providers.pricing import _PRICING, _normalize, parse_feed

_FEED = Path(__file__).resolve().parent.parent / "pricing.json"


def list_model_ids(base_url: str, api_key: str) -> list[str]:
    ids: list[str] = []
    params = {"limit": 1000}
    while True:
        req = Request(
            f"{base_url}/v1/models?{urlencode(params)}",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )
        with urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read())
        ids.extend(model["id"] for model in page["data"])
        if not page.get("has_more"):
            return ids
        params["after_id"] = page["last_id"]


def unpriced(model_ids: list[str], feed_raw: bytes) -> list[str]:
    feed = parse_feed(feed_raw)
    if feed is None:
        raise ValueError("pricing.json fails validation")
    known = set(_PRICING) | set(feed[0]) | set(json.loads(feed_raw).get("ignore", []))
    return sorted({_normalize(model_id) for model_id in model_ids} - known)


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    for key in unpriced(list_model_ids(base_url, api_key), _FEED.read_bytes()):
        print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
