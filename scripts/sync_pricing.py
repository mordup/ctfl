"""Bring pricing.json in line with Anthropic's pricing page.

Run by .github/workflows/pricing-sync.yml from the repo root with PYTHONPATH=.
Rewrites pricing.json when the page differs from what installs would use, and
prints a Markdown summary of the changes for the pull request body.

Entries are only added or changed, never removed: installs replace their
cached copy with this file, so a removed entry would unprice that model.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from ctfl.providers.pricing import _FAST_PRICING, _PRICING, _RATE_FIELDS, parse_feed

_PAGE_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
_FEED = Path(__file__).resolve().parent.parent / "pricing.json"

# Page column -> position in a rates tuple (input, output, cache_read, 5m, 1h).
_MAIN_COLUMNS = {
    "Base input tokens": 0,
    "Output tokens": 1,
    "Cache hits and refreshes": 2,
    "5m cache writes": 3,
    "1h cache writes": 4,
}
_FAST_COLUMNS = ["Model", "Input", "Output"]
_MIN_MAIN_ROWS = 5
_NAME_RE = re.compile(r"Claude ([A-Za-z]+) (\d+(?:\.\d+)*)")
_PRICE_RE = re.compile(r"\$(\d+(?:\.\d+)?) / MTok")
_SUP_RE = re.compile(r"<sup>.*?</sup>")

Rates = tuple[float, float, float, float, float]


class PageFormatError(Exception):
    """The pricing page no longer has the shape this parser expects."""


def _tables(md: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in md.splitlines():
        if line.startswith("|"):
            current.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _model_key(cell: str) -> str:
    # Rows read "Claude Opus 4.1 ([retired, ...](url))": the name is what
    # precedes the first parenthesis.
    match = _NAME_RE.fullmatch(cell.split(" (", 1)[0].strip())
    if match is None:
        raise PageFormatError(f"unrecognised model name: {cell!r}")
    family, version = match.groups()
    return f"{family.lower()}-{version.replace('.', '-')}"


def _price(cell: str) -> float:
    match = _PRICE_RE.fullmatch(_SUP_RE.sub("", cell).strip())
    if match is None:
        raise PageFormatError(f"unrecognised price: {cell!r}")
    return float(match.group(1))


def _find_table(md: str, header_match) -> list[list[str]]:
    found = [t for t in _tables(md) if header_match(t[0])]
    if len(found) != 1:
        raise PageFormatError(f"expected one matching table, found {len(found)}")
    return found[0]


def parse_page(md: str) -> tuple[dict[str, Rates], dict[str, Rates]]:
    """Read (standard, fast) rates from the pricing page's Markdown."""
    main = _find_table(md, lambda header: header[0] == "Model" and set(_MAIN_COLUMNS) <= set(header))
    header = main[0]
    standard: dict[str, Rates] = {}
    for row in main[2:]:
        rates = [0.0] * 5
        for column, position in _MAIN_COLUMNS.items():
            rates[position] = _price(row[header.index(column)])
        standard[_model_key(row[0])] = tuple(rates)
    if len(standard) < _MIN_MAIN_ROWS:
        raise PageFormatError(f"only {len(standard)} models in the pricing table")

    # The page lists only input and output for fast mode; caching multipliers
    # stack on top of it, so the cache rates keep the standard ratios.
    fast_table = _find_table(md, lambda header: header == _FAST_COLUMNS)
    fast: dict[str, Rates] = {}
    for row in fast_table[2:]:
        fast_input, fast_output = _price(row[1]), _price(row[2])
        for name in row[0].split(" / "):
            key = _model_key(name)
            if key not in standard:
                raise PageFormatError(f"fast mode row {key!r} has no standard price")
            base = standard[key]
            ratio = fast_input / base[0]
            fast[key] = (
                fast_input,
                fast_output,
                round(base[2] * ratio, 6),
                round(base[3] * ratio, 6),
                round(base[4] * ratio, 6),
            )
    return standard, fast


def sync(page: tuple[dict[str, Rates], dict[str, Rates]], feed_raw: bytes) -> tuple[dict, list[str]]:
    """Return the updated feed document and one summary line per change."""
    if parse_feed(feed_raw) is None:
        raise ValueError("pricing.json fails validation")
    doc = json.loads(feed_raw)
    ignore = set(doc.get("ignore", []))
    changes: list[str] = []
    for section, bundled, page_rates in (
        ("models", _PRICING, page[0]),
        ("fast", _FAST_PRICING, page[1]),
    ):
        entries = doc.setdefault(section, {})
        for key, rates in sorted(page_rates.items()):
            if key in ignore:
                continue
            current = entries.get(key)
            current = tuple(current[f] for f in _RATE_FIELDS) if current else bundled.get(key)
            if current == rates:
                continue
            entries[key] = dict(zip(_RATE_FIELDS, rates, strict=True))
            label = f"`{key}`" + (" (fast mode)" if section == "fast" else "")
            if current is None:
                changes.append(f"- {label}: new, {_describe(rates)}")
            else:
                changes.append(f"- {label}: {_describe(current)} → {_describe(rates)}")
    if changes:
        doc["updated"] = date.today().isoformat()
    return doc, changes


def _describe(rates: Rates) -> str:
    return ", ".join(f"{field} ${value:g}" for field, value in zip(_RATE_FIELDS, rates, strict=True))


def render(doc: dict) -> str:
    """Serialise the feed with one model per line, as the file is kept by hand."""
    lines = ["{"]
    for field in ("schema", "updated"):
        if field in doc:
            lines.append(f"  {json.dumps(field)}: {json.dumps(doc[field])},")
    for section in ("models", "fast"):
        entries = doc.get(section, {})
        if not entries:
            lines.append(f"  {json.dumps(section)}: {{}},")
            continue
        lines.append(f"  {json.dumps(section)}: {{")
        items = sorted(entries.items())
        for i, (key, rates) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            lines.append(f"    {json.dumps(key)}: {json.dumps(rates)}{comma}")
        lines.append("  },")
    lines.append(f"  \"ignore\": {json.dumps(doc.get('ignore', []))}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    url = os.environ.get("PRICING_PAGE_URL", _PAGE_URL)
    with urlopen(Request(url, headers={"User-Agent": "ctfl-pricing-sync"}), timeout=30) as resp:
        md = resp.read().decode("utf-8")
    doc, changes = sync(parse_page(md), _FEED.read_bytes())
    if not changes:
        return 0
    text = render(doc)
    if parse_feed(text.encode()) is None:
        raise ValueError("the updated pricing.json fails validation")
    _FEED.write_text(text)
    print(f"Prices on {_PAGE_URL.removesuffix('.md')} differ from what CTFL installs use:\n")
    print("\n".join(changes))
    print("\nCheck each line against the page before merging. Fast-mode cache rates are not "
          "on the page; they keep the standard cache-to-input ratio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
