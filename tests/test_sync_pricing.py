import importlib.util
import json
from pathlib import Path

import pytest

from ctfl.providers.pricing import parse_feed

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sync_pricing.py"
_spec = importlib.util.spec_from_file_location("sync_pricing", _SCRIPT)
sync_pricing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_pricing)

_MAIN_HEADER = (
    "| Model | Base input tokens | 5m cache writes | 1h cache writes "
    "| Cache hits and refreshes | Output tokens |\n"
    "| :-- | :-- | :-- | :-- | :-- | :-- |\n"
)
_ROWS = [
    "| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |",
    "| Claude Opus 5 | $5 / MTok | $6.25 / MTok | $10 / MTok | $0.50 / MTok | $25 / MTok |",
    "| Claude Opus 4.8 | $5 / MTok | $6.25 / MTok | $10 / MTok | $0.50 / MTok | $25 / MTok |",
    "| Claude Opus 4.1 ([retired, except on Bedrock](https://example.com/x)) "
    "| $15 / MTok | $18.75 / MTok | $30 / MTok | $1.50 / MTok | $75 / MTok |",
    "| Claude Sonnet 5 | $2 / MTok<sup>3</sup> | $2.50 / MTok | $4 / MTok | $0.20 / MTok "
    "| $10 / MTok<sup>3</sup> |",
]
_FAST = (
    "### Fast mode pricing\n\n"
    "| Model | Input | Output |\n"
    "| --- | --- | --- |\n"
    "| Claude Opus 5.5 | $8 / MTok | $40 / MTok |\n"
    "| Claude Opus 5 / Claude Opus 4.8 | $10 / MTok | $50 / MTok |\n"
)


def _page(rows=_ROWS, fast=_FAST) -> str:
    return "## Model pricing\n\n" + _MAIN_HEADER + "\n".join(rows) + "\n\n*<sup>notes</sup>*\n\n" + fast


def _feed(models=None, ignore=()) -> bytes:
    return json.dumps({
        "schema": 1, "updated": "2026-09-01", "models": models or {}, "fast": {}, "ignore": list(ignore),
    }).encode()


def test_parse_page_reads_standard_rates():
    standard, _ = sync_pricing.parse_page(_page())
    assert standard["opus-5-5"] == (4.0, 20.0, 0.2, 5.0, 8.0)
    assert standard["opus-4-1"] == (15.0, 75.0, 1.5, 18.75, 30.0)
    assert standard["sonnet-5"] == (2.0, 10.0, 0.2, 2.5, 4.0)


def test_parse_page_splits_shared_fast_rows_and_scales_cache_rates():
    _, fast = sync_pricing.parse_page(_page())
    assert fast["opus-5-5"] == (8.0, 40.0, 0.4, 10.0, 16.0)
    assert fast["opus-5"] == fast["opus-4-8"] == (10.0, 50.0, 1.0, 12.5, 20.0)


@pytest.mark.parametrize("page", [
    _page(rows=_ROWS[:3]),
    _page(rows=[*_ROWS, "| Claude Opus 6 | $5 per MTok | $6.25 / MTok | $10 / MTok | $0.50 / MTok | $25 / MTok |"]),
    _page(rows=[*_ROWS, "| Opus Next | $5 / MTok | $6.25 / MTok | $10 / MTok | $0.50 / MTok | $25 / MTok |"]),
    _page(fast=""),
    _page(fast=_FAST.replace("Claude Opus 5.5", "Claude Opus 9")),
    _page().replace("5m cache writes", "Cache writes"),
])
def test_parse_page_rejects_unexpected_shapes(page):
    with pytest.raises(sync_pricing.PageFormatError):
        sync_pricing.parse_page(page)


def test_parsed_page_matches_bundled_table_gives_no_changes():
    _, changes = sync_pricing.sync(sync_pricing.parse_page(_page()), _feed())
    assert changes == []


def test_new_model_is_added():
    page = sync_pricing.parse_page(_page(rows=[
        *_ROWS, "| Claude Quasar 9 | $1 / MTok | $1.25 / MTok | $2 / MTok | $0.10 / MTok | $5 / MTok |",
    ]))
    doc, changes = sync_pricing.sync(page, _feed())
    assert doc["models"]["quasar-9"] == {
        "input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write_5m": 1.25, "cache_write_1h": 2.0,
    }
    assert len(changes) == 1 and "`quasar-9`: new" in changes[0]
    assert doc["updated"] != "2026-09-01"


def test_changed_bundled_price_is_overridden():
    rows = [_ROWS[0].replace("$20 / MTok", "$18 / MTok"), *_ROWS[1:]]
    doc, changes = sync_pricing.sync(sync_pricing.parse_page(_page(rows=rows)), _feed())
    assert doc["models"]["opus-5-5"]["output"] == 18.0
    assert changes == [
        "- `opus-5-5`: input $4, output $20, cache_read $0.2, cache_write_5m $5, cache_write_1h $8"
        " → input $4, output $18, cache_read $0.2, cache_write_5m $5, cache_write_1h $8"
    ]


def test_feed_entries_are_never_removed():
    kept = {"input": 1, "output": 2, "cache_read": 0.1, "cache_write_5m": 1.25, "cache_write_1h": 2}
    doc, _ = sync_pricing.sync(sync_pricing.parse_page(_page()), _feed(models={"nova-1": kept}))
    assert doc["models"]["nova-1"] == kept


def test_ignored_models_are_skipped():
    page = sync_pricing.parse_page(_page(rows=[
        *_ROWS, "| Claude Quasar 9 | $1 / MTok | $1.25 / MTok | $2 / MTok | $0.10 / MTok | $5 / MTok |",
    ]))
    doc, changes = sync_pricing.sync(page, _feed(ignore=["quasar-9"]))
    assert changes == [] and "quasar-9" not in doc["models"]


def test_render_round_trips_through_the_app_parser():
    page = sync_pricing.parse_page(_page(rows=[
        *_ROWS, "| Claude Quasar 9 | $1 / MTok | $1.25 / MTok | $2 / MTok | $0.10 / MTok | $5 / MTok |",
    ]))
    doc, _ = sync_pricing.sync(page, _feed())
    text = sync_pricing.render(doc)
    assert parse_feed(text.encode()) is not None
    assert json.loads(text) == doc


def test_render_keeps_the_repo_file_unchanged():
    raw = sync_pricing._FEED.read_text()
    assert sync_pricing.render(json.loads(raw)) == raw
