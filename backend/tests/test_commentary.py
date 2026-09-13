"""The AI commentary path is exercised with a stub client (no API key needed)."""
import json
from types import SimpleNamespace

from fintea.model import build_model
from fintea.model.llm import SYSTEM, ai_commentary, commentary_key, payload_from_parts
from fintea.providers import load_dataset


class _StubMessages:
    def __init__(self, log):
        self.log = log

    def create(self, **kw):
        self.log.append(kw)
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"],
                               content=[SimpleNamespace(type="text", text="Revenue growth of 10.6% looks reasonable.")])


class _StubClient:
    def __init__(self):
        self.log = []
        self.beta = SimpleNamespace(messages=_StubMessages(self.log))
        self.messages = _StubMessages(self.log)


def test_commentary_request_and_cache_key():
    res = build_model(load_dataset("MSFT", "sample"), years=5)
    client = _StubClient()
    out = ai_commentary(res, client)
    assert out["status"] == "ok" and "reasonable" in out["text"] and out["key"] == commentary_key(res.summary)
    req = client.log[0]
    assert req["system"] == SYSTEM and req["fallbacks"] == "default" and req["max_tokens"] >= 1000
    body = req["messages"][0]["content"]
    assert body.startswith("Model JSON:")
    payload = json.loads(body.split("\n", 1)[1])
    assert payload["symbol"] == "MSFT" and "terminal_growth" in payload["assumptions"] and payload["checks"]
    assert payload == json.loads(json.dumps(payload_from_parts(res.summary, res.assumptions.to_json(), res.feedback), default=str))
    # the key is stable for the same picture and changes when the valuation moves materially
    s2 = dict(res.summary); s2["upside"] = (res.summary["upside"] or 0) + 0.2
    assert commentary_key(res.summary) == commentary_key(dict(res.summary)) != commentary_key(s2)
