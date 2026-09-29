import pytest

from ctfl.popup import _short_model


@pytest.mark.parametrize("model, label", [
    ("claude-opus-5-5", "Opus 5.5"),
    ("claude-fable-5-1", "Fable 5.1"),
    ("claude-opus-5", "Opus 5"),
    ("claude-opus-5-5[1m]", "Opus 5.5"),
    ("claude-opus-4-5-20251101", "Opus 4.5"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5"),
    ("opus-4-6", "Opus 4.6"),
    ("claude-3-5-sonnet-20241022", "Sonnet 3.5"),
    ("claude-3-opus-20240229", "Opus 3"),
])
def test_model_ids_read_as_model_names(model, label):
    assert _short_model(model) == label


@pytest.mark.parametrize("model", ["<synthetic>", "unknown"])
def test_pseudo_models_keep_their_name(model):
    assert _short_model(model).lower() == model
