from ctfl.providers.pricing import _match_pricing, _normalize, estimate_daily_cost

_OPUS_CURRENT = (5.00, 25.00, 0.50, 6.25)
_OPUS_LEGACY = (15.00, 75.00, 1.50, 18.75)
_SONNET = (3.00, 15.00, 0.30, 3.75)


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
    assert _match_pricing("claude-fable-5") == (10.00, 50.00, 1.00, 12.50)


def test_haiku_4_5():
    assert _match_pricing("claude-haiku-4-5-20251001") == (1.00, 5.00, 0.10, 1.25)


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


def test_unknown_model():
    assert _match_pricing("gpt-5") is None


def test_unknown_claude_family():
    assert _match_pricing("claude-quasar-9") is None


# --- estimate_daily_cost ---

def test_empty_mapping():
    assert estimate_daily_cost({}) is None


def test_single_model_arithmetic():
    # 1M input + 1M output on Opus 5 = $5.00 + $25.00
    cost = estimate_daily_cost({"claude-opus-5": (1_000_000, 1_000_000, 0, 0)})
    assert cost == 30.00


def test_cache_tokens_priced():
    # 1M cache reads + 1M cache writes on Opus 5 = $0.50 + $6.25
    cost = estimate_daily_cost({"claude-opus-5": (0, 0, 1_000_000, 1_000_000)})
    assert cost == 6.75


def test_multiple_known_models_sum():
    cost = estimate_daily_cost({
        "claude-opus-5": (1_000_000, 0, 0, 0),
        "claude-sonnet-5": (1_000_000, 0, 0, 0),
    })
    assert cost == 8.00


def test_unknown_model_suppresses_whole_day():
    # Regression: previously the first matched model set a "matched" flag and a
    # total was returned that silently omitted every unpriced model.
    cost = estimate_daily_cost({
        "claude-opus-5": (1_000_000, 0, 0, 0),
        "claude-quasar-9": (5_000_000, 0, 0, 0),
    })
    assert cost is None


def test_only_unknown_models():
    assert estimate_daily_cost({"gpt-5": (1_000_000, 0, 0, 0)}) is None


def test_zero_tokens_known_model():
    assert estimate_daily_cost({"claude-opus-5": (0, 0, 0, 0)}) == 0.0
