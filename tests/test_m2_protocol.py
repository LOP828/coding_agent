import json

import pytest

from coding_agent.isolated_verification import FORMAT, compare_outcome, parse_observation


def record(outcome=None):
    return {"format": FORMAT, "run_id": "fresh", "case_id": "case",
            "outcome": outcome or {"kind": "return", "value": {"provider": "openai"}}}


@pytest.mark.parametrize("raw", [
    b"", b"PASS", b"{}\n{}", b"\xff", b'{"run_id":"fresh","run_id":"fresh"}',
    json.dumps(record()).encode() + b"\n" + json.dumps(record()).encode(),
    json.dumps(record()).encode() + b"\nnoise",
    json.dumps({**record(), "run_id": "stale"}).encode(),
    json.dumps({**record(), "case_id": "another"}).encode(),
    json.dumps({**record(), "status": "PASS"}).encode(),
    json.dumps(record({"kind": "return", "value": float("nan")})).encode(),
    json.dumps(record({"kind": "return", "value": 123})).replace("123", "1e999").encode(),
    json.dumps(record({"kind": "exception", "type": "ValueError"})).encode(),
])
def test_invalid_observations_are_rejected(raw):
    with pytest.raises(ValueError):
        parse_observation(raw, "fresh", "case")


@pytest.mark.parametrize("expected,matches", [
    ({"kind": "exception", "type": "MissingProviderError"}, True),
    ({"kind": "exception", "type": "MissingProviderError", "message": "any text"}, True),
    ({"kind": "exception", "type": "MissingProviderError", "message": "different"}, False),
    ({"kind": "exception", "type": "ValueError"}, False),
    ({"kind": "return", "value": None}, False),
])
def test_exception_class_name_and_optional_message(expected, matches):
    observed = parse_observation(json.dumps(record({
        "kind": "exception", "type": "MissingProviderError", "message": "any text",
    })).encode(), "fresh", "case")
    assert compare_outcome(observed, expected) is matches


@pytest.mark.parametrize("value", [True, 1.0, "1", [True], {"value": True}])
def test_value_comparison_does_not_coerce_types(value):
    expected = [1] if isinstance(value, list) else {"value": 1} if isinstance(value, dict) else 1
    assert not compare_outcome({"kind": "return", "value": value}, {"kind": "return", "value": expected})
