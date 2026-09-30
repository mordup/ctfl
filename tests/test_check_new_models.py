import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_new_models.py"
_spec = importlib.util.spec_from_file_location("check_new_models", _SCRIPT)
check_new_models = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_new_models)

_RATES = {"input": 1, "output": 2, "cache_read": 0.1, "cache_write_5m": 1.25, "cache_write_1h": 2}


def _feed(models=(), ignore=()) -> bytes:
    return json.dumps({
        "schema": 1,
        "models": {m: _RATES for m in models},
        "ignore": list(ignore),
    }).encode()


def test_unpriced_lists_only_unknown_models():
    ids = ["claude-opus-5", "claude-quasar-9", "claude-nova-1"]
    assert check_new_models.unpriced(ids, _feed()) == ["nova-1", "quasar-9"]


def test_unpriced_normalizes_date_suffixed_ids():
    assert check_new_models.unpriced(["claude-haiku-4-5-20251001"], _feed()) == []


def test_unpriced_counts_feed_and_ignore_as_known():
    ids = ["claude-quasar-9", "claude-3-haiku-20240307"]
    assert check_new_models.unpriced(ids, _feed(models=["quasar-9"], ignore=["3-haiku"])) == []


def test_unpriced_rejects_invalid_feed():
    with pytest.raises(ValueError):
        check_new_models.unpriced(["claude-opus-5"], b"{}")


def test_repo_feed_is_readable_by_the_script():
    check_new_models.unpriced([], check_new_models._FEED.read_bytes())


_PAGES = {
    None: {"data": [{"id": "claude-a-1"}, {"id": "claude-b-1"}], "has_more": True,
           "last_id": "claude-b-1"},
    "claude-b-1": {"data": [{"id": "claude-c-1"}], "has_more": False, "last_id": "claude-c-1"},
}
_seen_keys: list[str] = []


class _ModelsApi(BaseHTTPRequestHandler):
    def do_GET(self):
        _seen_keys.append(self.headers["x-api-key"])
        after = parse_qs(urlparse(self.path).query).get("after_id", [None])[0]
        body = json.dumps(_PAGES[after]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_list_model_ids_follows_pagination():
    server = HTTPServer(("127.0.0.1", 0), _ModelsApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        ids = check_new_models.list_model_ids(f"http://127.0.0.1:{server.server_port}", "k")
    finally:
        server.shutdown()
    assert ids == ["claude-a-1", "claude-b-1", "claude-c-1"]
    assert _seen_keys == ["k", "k"]
