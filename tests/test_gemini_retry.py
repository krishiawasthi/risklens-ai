"""Retry and model-fallback behaviour of the real Gemini generator, using a
fake client. No network calls and no real waiting."""
from types import SimpleNamespace

import pytest
from google.genai import errors

from utils.llm_extractor import RETRY_WAITS, ExtractionError, Usage, configured_models, make_gemini_generator


def api_error(code, status):
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"code": code, "message": f"test {status}", "status": status}})


def ok_response(text='{"risks": []}'):
    return SimpleNamespace(
        text=text,
        candidates=[],
        prompt_feedback=None,
        usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=20),
    )


class FakeClient:
    """outcomes: {model_name: [exception or response, ...]} consumed in order."""

    def __init__(self, outcomes):
        self.outcomes = {m: list(v) for m, v in outcomes.items()}
        self.calls = []
        self.models = self

    def generate_content(self, model, **kwargs):
        self.calls.append(model)
        outcome = self.outcomes[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make(client, models, usage=None):
    waits, messages = [], []
    gen = make_gemini_generator(
        models=models, client=client, sleep=waits.append, on_retry=messages.append, usage=usage
    )
    return gen, waits, messages


UNAVAILABLE = [api_error(503, "UNAVAILABLE")] * (len(RETRY_WAITS) + 1)


def test_503_then_success_on_same_model():
    client = FakeClient({"m1": [api_error(503, "UNAVAILABLE"), ok_response()]})
    usage = Usage()
    gen, waits, messages = make(client, ["m1"], usage)
    assert gen("sys", "prompt") == '{"risks": []}'
    assert waits == [RETRY_WAITS[0]]
    assert usage.models_used == ["m1"] and usage.prompt_tokens == 100


def test_falls_back_to_next_model_when_first_stays_unavailable():
    client = FakeClient({"m1": UNAVAILABLE, "m2": [ok_response()]})
    usage = Usage()
    gen, waits, messages = make(client, ["m1", "m2"], usage)
    gen("sys", "prompt")
    assert client.calls == ["m1"] * len(UNAVAILABLE) + ["m2"]
    assert usage.models_used == ["m2"]
    assert any("Switching to m2" in m for m in messages)


def test_unknown_model_is_skipped():
    client = FakeClient({"old-model": [api_error(404, "NOT_FOUND")], "m2": [ok_response()]})
    gen, _, _ = make(client, ["old-model", "m2"])
    gen("sys", "prompt")
    assert client.calls == ["old-model", "m2"]


def test_all_models_unavailable():
    client = FakeClient({"m1": UNAVAILABLE, "m2": UNAVAILABLE})
    gen, _, _ = make(client, ["m1", "m2"])
    with pytest.raises(ExtractionError, match="No configured Gemini model"):
        gen("sys", "prompt")


def test_bad_request_stops_without_trying_other_models():
    client = FakeClient({"m1": [api_error(400, "INVALID_ARGUMENT")], "m2": [ok_response()]})
    gen, _, _ = make(client, ["m1", "m2"])
    with pytest.raises(ExtractionError, match="rejected"):
        gen("sys", "prompt")
    assert client.calls == ["m1"]


def test_empty_response_raises():
    client = FakeClient({"m1": [ok_response(text=None)]})
    gen, _, _ = make(client, ["m1"])
    with pytest.raises(ExtractionError, match="no text"):
        gen("sys", "prompt")


def test_model_list_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODELS", "a-model, b-model")
    assert configured_models() == ["a-model", "b-model"]
    monkeypatch.delenv("GEMINI_MODELS")
    monkeypatch.setenv("GEMINI_MODEL", "single-model")
    assert configured_models() == ["single-model"]
