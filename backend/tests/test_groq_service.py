from types import SimpleNamespace
import pytest
from pydantic import BaseModel

from app.services.groq import (
    GroqAPIError,
    GroqConfigurationError,
    GroqService,
    GroqValidationError,
)


class SampleSchema(BaseModel):
    score: int
    reason: str


class _FakeCompletions:
    def __init__(self, responses: list[object]):
        self._responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        content, tokens = item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(total_tokens=tokens),
        )


class _FakeGroqClient:
    def __init__(self, responses: list[object]):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def test_complete_json_valid_first_try():
    fake = _FakeGroqClient([('{"score": 88, "reason": "Strong Python fit"}', 120)])
    svc = GroqService(api_key="test-key", model="llama-3.3-70b-versatile", client=fake)

    res = svc.complete_json("sys", "user", SampleSchema)
    assert res.data.score == 88
    assert res.data.reason == "Strong Python fit"
    assert res.tokens_used == 120
    assert res.repaired is False
    assert res.attempts == 1


def test_complete_json_repairs_once_on_invalid_json():
    fake = _FakeGroqClient(
        [
            ('{"score": "not_an_int", "reason": "bad"}', 100),
            ('{"score": 92, "reason": "repaired"}', 80),
        ]
    )
    svc = GroqService(api_key="test-key", client=fake)

    res = svc.complete_json("sys", "user", SampleSchema)
    assert res.data.score == 92
    assert res.repaired is True
    assert res.tokens_used == 180
    assert res.attempts == 2


def test_complete_json_raises_after_failed_repair():
    fake = _FakeGroqClient(
        [
            ('{"wrong": 1}', 50),
            ('{"still_wrong": 2}', 50),
        ]
    )
    svc = GroqService(api_key="test-key", client=fake)

    with pytest.raises(GroqValidationError):
        svc.complete_json("sys", "user", SampleSchema)


def test_complete_json_retries_transient_timeout():
    fake = _FakeGroqClient(
        [
            TimeoutError("timed out"),
            ('{"score": 75, "reason": "recovered"}', 95),
        ]
    )
    svc = GroqService(api_key="test-key", max_retries=2, backoff_seconds=0.0, client=fake)

    res = svc.complete_json("sys", "user", SampleSchema)
    assert res.data.score == 75
    assert res.attempts == 2


def test_complete_json_exhausts_retries():
    fake = _FakeGroqClient([TimeoutError("1"), TimeoutError("2"), TimeoutError("3")])
    svc = GroqService(api_key="test-key", max_retries=2, backoff_seconds=0.0, client=fake)

    with pytest.raises(GroqAPIError):
        svc.complete_json("sys", "user", SampleSchema)


def test_missing_api_key_raises_configuration_error():
    svc = GroqService(api_key="")
    with pytest.raises(GroqConfigurationError):
        svc.complete_json("sys", "user", SampleSchema)
