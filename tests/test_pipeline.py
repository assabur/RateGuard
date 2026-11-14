from dataclasses import replace
from datetime import date

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from rateguard.api import create_app, current_view
from rateguard.demo import payloads
from rateguard.pipeline import run_pipeline
from rateguard.providers import NS
from rateguard.storage import Repository

from .conftest import DAY


def mock_client(fail_fred=False, broken_xml=False, delta=None):
    data = list(payloads(DAY))

    def handler(request):
        if request.url.host == "home.treasury.gov":
            if broken_xml:
                return httpx.Response(200, content=b"not-xml")
            if request.url.params["field_tdr_date_value"] != str(DAY.year):
                return httpx.Response(200, content=f'<feed xmlns="{NS["atom"]}"/>'.encode())
            return httpx.Response(200, content=data[0][2])
        if fail_fred:
            return httpx.Response(403)
        tenor = int(request.url.params["series_id"][3:])
        body = next(body for provider, t, body, _ in data if provider == "fred" and t == tenor)
        if delta and tenor == 10:
            body = body.replace(b'"5.13"', b'"5.14"')
        return httpx.Response(200, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_demo_end_to_end_and_run_history(postgres_settings):
    settings = postgres_settings
    first = run_pipeline(settings, DAY, "demo")
    second = run_pipeline(settings, DAY, "demo")
    assert first["run_id"] != second["run_id"]
    assert second["previous_run_id"] == first["run_id"]
    assert first["status"] == "CRITICAL"
    assert first["reconciliation"][2]["absolute_difference_bps"] == 2
    assert first["reconciliation"][2]["status"] == "OK"
    assert not any(r["usable_as_of"] for r in first["reconciliation"])
    frame = pd.read_parquet(first["artifacts_dir"] + "/observations.parquet")
    assert len(frame) == 16
    repository = Repository(settings)
    try:
        assert repository.latest(mode="live") is None
        assert repository.latest(DAY, "demo")["run_id"] == second["run_id"]
        assert len(repository.history("demo")) == 2
        assert repository.by_id(first["run_id"])["run_id"] == first["run_id"]
    finally:
        repository.close()


def test_live_http_provenance_and_revision(postgres_settings):
    settings = postgres_settings
    with mock_client() as client:
        first = run_pipeline(settings, DAY, client=client)
    with mock_client(delta=True) as client:
        second = run_pipeline(settings, DAY, client=client)
    assert first["ingestion_errors"] == []
    assert first["reconciliation"][2]["usable_as_of"] is True
    assert second["points"][6]["issues"][0]["code"] == "observed_revision"
    assert second["reconciliation"][2]["usable_as_of"] is False
    assert second["previous_run_id"] == first["run_id"]


def test_provider_failure_persists_critical_partial_run(postgres_settings):
    settings = postgres_settings
    with mock_client(fail_fred=True) as client:
        report = run_pipeline(settings, DAY, client=client)
    assert report["status"] == "CRITICAL"
    assert len(report["ingestion_errors"]) == 4
    assert report["curves"][0]["shape"] == "NORMAL"
    assert report["curves"][1]["shape"] == "INCOMPLETE"
    assert all(r["absolute_difference_bps"] is None for r in report["reconciliation"])


def test_malformed_xml_is_archived_and_recorded(postgres_settings):
    settings = postgres_settings
    with mock_client(broken_xml=True) as client:
        report = run_pipeline(settings, DAY, client=client)
    assert report["status"] == "CRITICAL"
    assert report["ingestion_errors"][0]["provider"] == "treasury"
    from pathlib import Path

    assert list(Path(report["artifacts_dir"]).glob("raw/treasury-*.xml"))


def test_missing_key_fails_before_creating_data(settings):
    with pytest.raises(ValueError, match="FRED_API_KEY"):
        run_pipeline(replace(settings, fred_api_key=""), DAY)
    assert not settings.data_dir.exists()


def test_api_demo_isolation_filters_and_validation(postgres_settings):
    settings = postgres_settings
    report = run_pipeline(settings, DAY, "demo")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/report").status_code == 404
        assert client.get("/report?mode=demo").json()["run_id"] == report["run_id"]
        assert client.get("/reconciliation?mode=demo").json()["usable_today"] is False
        assert len(client.get("/curves?mode=demo").json()["curves"]) == 2
        assert client.get("/quality?mode=demo").json()["points"]
        assert client.get("/runs").json() == []
        assert len(client.get("/runs?mode=demo").json()) == 1
        assert client.get(f"/runs/{report['run_id']}").json()["mode"] == "demo"
        assert client.get("/runs/not-a-run").status_code == 404
        assert client.get("/report?mode=demo&as_of=2025-01-09").status_code == 404
        assert client.get("/report?mode=nope").status_code == 422
        assert client.get("/report?as_of=invalid").status_code == 422
        assert client.get("/runs?limit=99999").status_code == 422


def test_dashboard_and_assets_available_without_ingestion(postgres_settings):
    settings = postgres_settings
    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert 'lang="fr"' in page.text
        for path, content_type in (
            ("/static/dashboard.css", "text/css"),
            ("/static/dashboard.js", "javascript"),
        ):
            asset = client.get(path)
            assert asset.status_code == 200
            assert content_type in asset.headers["content-type"]
        assert client.get("/report").status_code == 404
        assert client.get("/runs").json() == []
        assert client.get("/docs").status_code == 200
        assert "/" not in client.get("/openapi.json").json()["paths"]


def test_latest_uses_market_date_before_ingestion_time(postgres_settings):
    settings = postgres_settings
    future = date(2025, 1, 10)
    newer = run_pipeline(settings, future, "demo")
    run_pipeline(settings, DAY, "demo")
    repository = Repository(settings)
    try:
        assert repository.latest(mode="demo")["run_id"] == newer["run_id"]
    finally:
        repository.close()


def test_current_freshness_recomputed(settings):
    report = {"as_of": str(DAY), "usable_as_of": True}
    assert current_view(report, settings, DAY)["usable_today"] is True
    assert current_view(report, settings, date(2025, 1, 12))["usable_today"] is True
    assert current_view(report, settings, date(2025, 1, 13))["usable_today"] is False
    assert current_view(report, settings, date(2025, 1, 7))["usable_today"] is False


def test_total_provider_outage_persists_empty_snapshot(postgres_settings):
    settings = postgres_settings
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
        report = run_pipeline(settings, DAY, client=client)
    assert report["status"] == "CRITICAL"
    assert len(report["ingestion_errors"]) == 6  # two calendar years and four FRED series
    assert pd.read_parquet(report["artifacts_dir"] + "/observations.parquet").empty
    assert not any(r["usable_as_of"] for r in report["reconciliation"])


def test_database_run_and_observations_commit_atomically(postgres_settings, observations):
    settings = postgres_settings
    from sqlalchemy.exc import IntegrityError

    report = run_pipeline(settings, DAY, "demo")
    repository = Repository(settings)
    failed_report = {**report, "run_id": "should-rollback"}
    try:
        with pytest.raises(IntegrityError):
            repository.save(failed_report, [replace(observations[0], provider=None)])
        assert repository.by_id("should-rollback") is None
    finally:
        repository.close()
