import json
from pathlib import Path

import httpx
import pytest

from rateguard.providers import (
    Collector,
    Payload,
    ProviderError,
    parse_fred,
    parse_treasury,
    parse_value,
)

from .conftest import NOW

FIXTURES = Path(__file__).parent / "fixtures"


def test_treasury_namespaces_and_percent_values():
    rows = parse_treasury(Payload((FIXTURES / "treasury.xml").read_bytes(), NOW, "raw/xml"))
    assert len(rows) == 4
    assert rows[2].yield_pct == 5.15
    assert rows[2].observation_date.isoformat() == "2025-01-08"
    assert rows[2].source_id == "BC_10YEAR"


def test_fred_missing_value_and_realtime_provenance():
    rows = parse_fred(Payload((FIXTURES / "fred.json").read_bytes(), NOW, "raw/json"), 10)
    assert rows[0].yield_pct is None
    assert rows[0].parse_issue == "missing_value"
    assert rows[1].yield_pct == 5.13
    assert rows[1].realtime_start == "2025-01-09"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (".", "missing_value"),
        (None, "missing_value"),
        ("NaN", "non_finite"),
        ("Infinity", "non_finite"),
        ("oops", "invalid_number"),
    ],
)
def test_invalid_numbers(text, code):
    assert parse_value(text) == (None, code)


def test_fred_truncated_response_is_rejected():
    body = json.dumps({"count": 3, "observations": []}).encode()
    with pytest.raises(ProviderError, match="truncated"):
        parse_fred(Payload(body, NOW, "raw/json"), 2)


def test_treasury_rejects_html():
    with pytest.raises(ProviderError, match="Atom"):
        parse_treasury(Payload(b"<html>blocked</html>", NOW, "raw/xml"))


def test_http_retries_and_secret_redaction(tmp_path, monkeypatch):
    monkeypatch.setattr("rateguard.providers.time.sleep", lambda _: None)
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(503 if len(attempts) < 3 else 200, json={"observations": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = Collector(client, tmp_path, "secret-api-key")
        assert collector.fred(2, NOW.date(), NOW.date()) == []
    assert len(attempts) == 3
    metadata = (tmp_path / "fred-DGS2.json.meta.json").read_text()
    assert "secret-api-key" not in metadata
    assert "api_key" not in metadata
    assert json.loads(metadata)["sha256"]


def test_client_error_does_not_retry_or_expose_key(tmp_path):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(400, text="secret-api-key")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as exc:
            Collector(client, tmp_path, "secret-api-key").fred(2, NOW.date(), NOW.date())
    assert "secret-api-key" not in str(exc.value)
    assert len(attempts) == 1
