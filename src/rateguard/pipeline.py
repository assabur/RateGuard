import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from xml.etree.ElementTree import ParseError

import httpx
import pandas as pd
from defusedxml.common import DefusedXmlException

from .analytics import evaluate
from .config import Settings
from .demo import payloads
from .models import TENORS, Observation
from .providers import Collector, Payload, ProviderError, parse_fred, parse_treasury
from .storage import Repository


def run_pipeline(settings: Settings, as_of: date, mode="live", client=None):
    if mode not in {"live", "demo"}:
        raise ValueError("Unknown ingestion mode")
    if mode == "live" and not settings.fred_api_key:
        raise ValueError("Configure FRED_API_KEY in .env before live ingestion")
    run_id = str(uuid4())
    created_at = datetime.now(UTC)
    run_dir = settings.data_dir / mode / "runs" / run_id
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True)
    rows = []
    errors = []
    # Small window for freshness and daily-change checks, including the prior year in January.
    start = as_of - timedelta(days=max(14, settings.max_age_days + 1))
    if mode == "demo":
        for provider, tenor, body, extension in payloads(as_of):
            path = raw_dir / f"{provider}-{tenor or 'curve'}.{extension}"
            path.write_bytes(body)
            path.with_suffix(path.suffix + ".meta.json").write_text(
                json.dumps(
                    {
                        "synthetic": True,
                        "retrieved_at": created_at.isoformat(),
                        "sha256": hashlib.sha256(body).hexdigest(),
                    },
                    indent=2,
                )
            )
            payload = Payload(body, created_at, str(path))
            rows.extend(
                parse_treasury(payload) if provider == "treasury" else parse_fred(payload, tenor)
            )
    else:
        owned_client = client is None
        http = client or httpx.Client(
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=True,
            headers={"User-Agent": "rateguard/0.1.0"},
        )
        collector = Collector(http, raw_dir, settings.fred_api_key)
        try:
            # A source failure still produces a persisted CRITICAL run and retains other sources.
            for year in range(start.year, as_of.year + 1):
                try:
                    rows.extend(collector.treasury(year))
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    RuntimeError,
                    ParseError,
                    DefusedXmlException,
                ) as exc:
                    errors.append(
                        {
                            "provider": "treasury",
                            "source": str(year),
                            "error_type": type(exc).__name__,
                            "detail": str(exc)
                            if isinstance(exc, ProviderError)
                            else "Invalid source payload",
                        }
                    )
            for tenor in TENORS:
                try:
                    rows.extend(collector.fred(tenor, start, as_of))
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    RuntimeError,
                    ParseError,
                    DefusedXmlException,
                ) as exc:
                    errors.append(
                        {
                            "provider": "fred",
                            "source": f"DGS{tenor}",
                            "error_type": type(exc).__name__,
                            "detail": str(exc)
                            if isinstance(exc, ProviderError)
                            else "Invalid source payload",
                        }
                    )
        finally:
            if owned_client:
                http.close()
    # Treasury responses cover whole years. Normalize only the requested window; keep raw intact.
    rows = [row for row in rows if start <= row.observation_date <= as_of]
    repository = Repository(settings)
    try:
        prior = repository.latest(as_of, mode)
        report = evaluate(rows, as_of, settings, prior)
        report.update(
            {
                "schema_version": 1,
                "run_id": run_id,
                "as_of": str(as_of),
                "mode": mode,
                "created_at": created_at.isoformat(),
                "window_start": str(start),
                "ingestion_errors": errors,
                "thresholds": {
                    "ok_bps": settings.ok_bps,
                    "warning_bps": settings.warning_bps,
                    "max_age_days": settings.max_age_days,
                    "jump_bps": settings.jump_bps,
                },
                "previous_run_id": prior["run_id"] if prior else None,
                "artifacts_dir": str(run_dir),
            }
        )
        if errors:
            report["status"] = "CRITICAL"
        report["usable_as_of"] = report["status"] == "OK" and mode == "live"
        for item in report["reconciliation"]:
            item["usable_as_of"] = item["status"] == "OK" and mode == "live" and not errors
        records = [row.record() for row in rows]
        frame = pd.DataFrame(records, columns=list(Observation.__dataclass_fields__))
        # Write normalized data and analytics as portable snapshots before committing the run.
        frame["observation_date"] = pd.to_datetime(frame["observation_date"])
        frame["retrieved_at"] = pd.to_datetime(frame["retrieved_at"], utc=True)
        frame.to_parquet(run_dir / "observations.parquet", index=False)
        pd.DataFrame(report["reconciliation"]).to_parquet(
            run_dir / "reconciliation.parquet", index=False
        )
        (run_dir / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        repository.save(report, rows)
        return report
    finally:
        repository.close()
