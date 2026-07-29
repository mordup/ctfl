from ctfl.providers.pricing import _match_pricing, _normalize, estimate_daily_cost

_OPUS_CURRENT = (5.00, 25.00, 0.50, 6.25, 10.00)
_OPUS_LEGACY = (15.00, 75.00, 1.50, 18.75, 30.00)
_SONNET = (3.00, 15.00, 0.30, 3.75, 6.00)


# --- _normalize ---

def test_normalize_strips_claude_prefix():
    assert _normalize("claude-opus-5") == "opus-5"


def test_normalize_strips_date_suffix():
    assert _normalize("claude-opus-4-5-20251101") == "opus-4-5"


def test_normalize_strips_variant_suffix():
    assert _normalize("claude-opus-5[1m]") == "opus-5"


# --- _match_pricing: current models ---

def test_opus_5():
    assert _match_pricing("claude-opus-5") == _OPUS_CURRENT


def test_opus_5_long_context_variant():
    assert _match_pricing("claude-opus-5[1m]") == _OPUS_CURRENT


def test_sonnet_5():
    assert _match_pricing("claude-sonnet-5") == _SONNET


def test_fable_5():
    assert _match_pricing("claude-fable-5") == (10.00, 50.00, 1.00, 12.50, 20.00)


def test_haiku_4_5():
    assert _match_pricing("claude-haiku-4-5-20251001") == (1.00, 5.00, 0.10, 1.25, 2.00)


def test_opus_4_8_uses_current_tier():
    assert _match_pricing("claude-opus-4-8") == _OPUS_CURRENT


def test_opus_4_5_uses_current_tier():
    assert _match_pricing("claude-opus-4-5-20251101") == _OPUS_CURRENT


def test_sonnet_4_6():
    assert _match_pricing("claude-sonnet-4-6") == _SONNET


# --- _match_pricing: longest-prefix-wins ---

def test_opus_4_1_gets_legacy_not_current_tier():
    # "opus-4-1" must win over the shorter "opus-4" key, and must not be
    # captured by the current-tier entries.
    assert _match_pricing("claude-opus-4-1-20250805") == _OPUS_LEGACY


def test_bare_opus_4_gets_legacy():
    assert _match_pricing("claude-opus-4-20250514") == _OPUS_LEGACY


def test_unpriced_point_release_fails_closed():
    # Regression: prefix matching handed claude-opus-4-9 the legacy $15/$75
    # tier via the bare "opus-4" entry, the opposite of failing closed.
    assert _match_pricing("claude-opus-4-9") is None


def test_unpriced_point_release_does_not_inherit_current_tier():
    assert _match_pricing("claude-opus-5-1") is None
    assert _match_pricing("claude-sonnet-5-1") is None


def test_unknown_model():
    assert _match_pricing("gpt-5") is None


def test_unknown_claude_family():
    assert _match_pricing("claude-quasar-9") is None


# --- estimate_daily_cost ---

def test_empty_mapping():
    assert estimate_daily_cost({}) is None


def test_single_model_arithmetic():
    # 1M input + 1M output on Opus 5 = $5.00 + $25.00
    cost = estimate_daily_cost({("claude-opus-5", "standard"): (1_000_000, 1_000_000, 0, 0, 0)})
    assert cost == 30.00


def test_cache_tokens_priced():
    # 1M cache reads + 1M cache writes on Opus 5 = $0.50 + $6.25
    cost = estimate_daily_cost({("claude-opus-5", "standard"): (0, 0, 1_000_000, 1_000_000, 0)})
    assert cost == 6.75


def test_multiple_known_models_sum():
    cost = estimate_daily_cost({
        ("claude-opus-5", "standard"): (1_000_000, 0, 0, 0, 0),
        ("claude-sonnet-5", "standard"): (1_000_000, 0, 0, 0, 0),
    })
    assert cost == 8.00


def test_unknown_model_suppresses_whole_day():
    # Regression: previously the first matched model set a "matched" flag and a
    # total was returned that silently omitted every unpriced model.
    cost = estimate_daily_cost({
        ("claude-opus-5", "standard"): (1_000_000, 0, 0, 0, 0),
        ("claude-quasar-9", "standard"): (5_000_000, 0, 0, 0, 0),
    })
    assert cost is None


def test_only_unknown_models():
    assert estimate_daily_cost({("gpt-5", "standard"): (1_000_000, 0, 0, 0, 0)}) is None


def test_zero_tokens_known_model():
    assert estimate_daily_cost({("claude-opus-5", "standard"): (0, 0, 0, 0, 0)}) == 0.0


# --- cache-write TTL tiers ---

def test_1h_cache_write_costs_2x_input():
    # Opus 5 input is $5/MTok, so a 1-hour write is $10/MTok.
    cost = estimate_daily_cost({("claude-opus-5", "standard"): (0, 0, 0, 0, 1_000_000)})
    assert cost == 10.00


def test_5m_cache_write_costs_1_25x_input():
    cost = estimate_daily_cost({("claude-opus-5", "standard"): (0, 0, 0, 1_000_000, 0)})
    assert cost == 6.25


def test_cache_write_tiers_are_not_interchangeable():
    five_m = estimate_daily_cost({("claude-opus-5", "standard"): (0, 0, 0, 1_000_000, 0)})
    one_h = estimate_daily_cost({("claude-opus-5", "standard"): (0, 0, 0, 0, 1_000_000)})
    assert one_h > five_m
    assert one_h / five_m == 1.6  # 2.0x vs 1.25x


def test_mixed_ttl_writes_sum():
    # 800k at 1h ($10/MTok) + 200k at 5m ($6.25/MTok)
    cost = estimate_daily_cost({("claude-opus-5", "standard"): (0, 0, 0, 200_000, 800_000)})
    assert cost == 8.00 + 1.25


# --- zero-token pseudo-models must not veto the day ---

def test_synthetic_pseudo_model_does_not_suppress_day():
    # Regression: "<synthetic>" is unpriced but carries no tokens, so it must
    # not suppress an otherwise fully-priced day.
    cost = estimate_daily_cost({
        ("claude-opus-5", "standard"): (1_000_000, 0, 0, 0, 0),
        ("<synthetic>", "standard"): (0, 0, 0, 0, 0),
    })
    assert cost == 5.00


def test_unknown_fallback_model_does_not_suppress_day():
    # _parse_jsonl defaults a missing model name to "unknown".
    cost = estimate_daily_cost({
        ("claude-opus-5", "standard"): (1_000_000, 0, 0, 0, 0),
        ("unknown", "standard"): (0, 0, 0, 0, 0),
    })
    assert cost == 5.00


def test_unpriced_model_with_tokens_still_suppresses():
    # The zero-token exemption must not weaken fail-closed for real usage.
    cost = estimate_daily_cost({
        ("claude-opus-5", "standard"): (1_000_000, 0, 0, 0, 0),
        ("<synthetic>", "standard"): (0, 0, 0, 0, 1),
    })
    assert cost is None


def test_only_zero_token_pseudo_models():
    assert estimate_daily_cost({("<synthetic>", "standard"): (0, 0, 0, 0, 0)}) == 0.0


# --- fast mode ---

_OPUS_FAST = (10.00, 50.00, 1.00, 12.50, 20.00)


def test_fast_mode_opus_5():
    assert _match_pricing("claude-opus-5", speed="fast") == _OPUS_FAST


def test_fast_mode_opus_4_8():
    assert _match_pricing("claude-opus-4-8", speed="fast") == _OPUS_FAST


def test_fast_mode_is_double_standard_for_opus_5():
    std = _match_pricing("claude-opus-5")
    fast = _match_pricing("claude-opus-5", speed="fast")
    assert all(f == s * 2 for f, s in zip(fast, std, strict=True))


def test_fast_mode_unsupported_model_bills_standard():
    # Opus 4.6 accepts speed="fast" but runs and bills at standard rates.
    assert _match_pricing("claude-opus-4-6", speed="fast") == _OPUS_CURRENT


def test_fast_mode_on_sonnet_bills_standard():
    assert _match_pricing("claude-sonnet-5", speed="fast") == _SONNET


def test_standard_speed_is_the_default():
    assert _match_pricing("claude-opus-5") == _match_pricing("claude-opus-5", speed="standard")


def test_same_model_at_both_speeds_priced_separately():
    cost = estimate_daily_cost({
        ("claude-opus-5", "standard"): (1_000_000, 0, 0, 0, 0),
        ("claude-opus-5", "fast"): (1_000_000, 0, 0, 0, 0),
    })
    assert cost == 5.00 + 10.00


# --- Sonnet 5 introductory pricing ---

_SONNET_5_INTRO = (2.00, 10.00, 0.20, 2.50, 4.00)


def test_sonnet_5_intro_rate_within_window():
    assert _match_pricing("claude-sonnet-5", date="2026-07-29") == _SONNET_5_INTRO


def test_sonnet_5_intro_rate_on_last_day():
    assert _match_pricing("claude-sonnet-5", date="2026-08-31") == _SONNET_5_INTRO


def test_sonnet_5_standard_rate_after_window():
    assert _match_pricing("claude-sonnet-5", date="2026-09-01") == _SONNET


def test_sonnet_5_without_date_uses_standard():
    # Undated callers get the durable rate rather than an expiring promotion.
    assert _match_pricing("claude-sonnet-5") == _SONNET


def test_intro_pricing_does_not_leak_to_other_models():
    assert _match_pricing("claude-sonnet-4-6", date="2026-07-29") == _SONNET
    assert _match_pricing("claude-opus-5", date="2026-07-29") == _OPUS_CURRENT


def test_estimate_uses_intro_rate_for_dated_day():
    tokens = {("claude-sonnet-5", "standard"): (1_000_000, 1_000_000, 0, 0, 0)}
    assert estimate_daily_cost(tokens, date="2026-08-15") == 12.00  # $2 + $10


def test_estimate_uses_standard_rate_after_cutover():
    tokens = {("claude-sonnet-5", "standard"): (1_000_000, 1_000_000, 0, 0, 0)}
    assert estimate_daily_cost(tokens, date="2026-09-01") == 18.00  # $3 + $15
