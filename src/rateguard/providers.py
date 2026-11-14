"""HTTP collection and parsers; archive successful bodies before attempting normalization."""

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from defusedxml import ElementTree

from .models import SERIES, TENORS, Observation

TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
)
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
}


class ProviderError(RuntimeError):
    """Safe, sanitized errors: never include request URLs carrying an API key."""


@dataclass(frozen=True)
class Payload:
    body: bytes
    retrieved_at: datetime
    raw_file: str


def parse_value(text):
    if text is None or str(text).strip() in {"", ".", "N/A", "ND"}:
        return None, "missing_value"
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None, "invalid_number"
    if not math.isfinite(value):
        return None, "non_finite"
    return value, None


def parse_treasury(payload: Payload) -> list[Observation]:
    root = ElementTree.fromstring(payload.body)
    if root.tag != f"{{{NS['atom']}}}feed":
        raise ProviderError("Treasury: expected an Atom XML feed")
    if root.find("atom:link[@rel='next']", NS) is not None:
        raise ProviderError("Treasury: truncated response; pagination required")
    result = []
    entries = root.findall("atom:entry", NS)
    for entry in entries:
        props = entry.find(".//m:properties", NS)
        if props is None:
            raise ProviderError("Treasury: properties missing")
        text_date = props.findtext("d:NEW_DATE", namespaces=NS)
        if not text_date:
            raise ProviderError("Treasury: observation date missing")
        day = date.fromisoformat(text_date[:10])
        for tenor in TENORS:
            value, issue = parse_value(props.findtext(f"d:BC_{tenor}YEAR", namespaces=NS))
            result.append(
                Observation(
                    "treasury",
                    day,
                    tenor,
                    value,
                    payload.retrieved_at,
                    f"BC_{tenor}YEAR",
                    payload.raw_file,
                    parse_issue=issue,
                )
            )
    return result


def parse_fred(payload: Payload, tenor: int) -> list[Observation]:
    body = json.loads(payload.body)
    if not isinstance(body, dict) or not isinstance(body.get("observations"), list):
        raise ProviderError("FRED: expected an observations array")
    rows = body["observations"]
    if int(body.get("count", len(rows))) != len(rows):
        raise ProviderError("FRED: truncated response; pagination required")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderError("FRED: invalid observation object")
        value, issue = parse_value(row.get("value"))
        result.append(
            Observation(
                "fred",
                date.fromisoformat(row["date"]),
                tenor,
                value,
                payload.retrieved_at,
                SERIES[tenor],
                payload.raw_file,
                row.get("realtime_start"),
                row.get("realtime_end"),
                issue,
            )
        )
    return result


class Collector:
    def __init__(self, client: httpx.Client, raw_dir: Path, api_key: str):
        self.client = client
        self.raw_dir = raw_dir
        self.api_key = api_key

    def download(self, name: str, url: str, params: dict, extension: str) -> Payload:
        # Three bounded attempts for network failures, 429 and server errors only.
        for attempt in range(3):
            try:
                response = self.client.get(url, params=params)
            except httpx.RequestError:
                if attempt < 2:
                    time.sleep(0.25 * 2**attempt)
                    continue
                raise ProviderError(f"{name}: network failure after 3 attempts") from None
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    time.sleep(0.25 * 2**attempt)
                    continue
            if not response.is_success:
                raise ProviderError(f"{name}: HTTP {response.status_code}")
            now = datetime.now(UTC)
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            path = self.raw_dir / f"{name}.{extension}"
            path.write_bytes(response.content)
            # Drop credentials from provenance. Do not serialize response.request.url.
            safe_params = {key: val for key, val in params.items() if key != "api_key"}
            metadata = {
                "endpoint": url,
                "params": safe_params,
                "retrieved_at": now.isoformat(),
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "status_code": response.status_code,
            }
            path.with_suffix(path.suffix + ".meta.json").write_text(
                json.dumps(metadata, indent=2),
                encoding="utf-8",
            )
            return Payload(response.content, now, str(path))
        raise ProviderError(f"{name}: retries exhausted")

    def treasury(self, year: int):
        return parse_treasury(
            self.download(
                f"treasury-{year}",
                TREASURY_URL,
                {"data": "daily_treasury_yield_curve", "field_tdr_date_value": year},
                "xml",
            )
        )

    def fred(self, tenor: int, start: date, end: date):
        if not self.api_key:
            raise ProviderError("FRED: FRED_API_KEY is required for live ingestion")
        return parse_fred(
            self.download(
                f"fred-{SERIES[tenor]}",
                FRED_URL,
                {
                    "series_id": SERIES[tenor],
                    "api_key": self.api_key,
                    "file_type": "json",
                    "observation_start": start.isoformat(),
                    "observation_end": end.isoformat(),
                    "units": "lin",
                    "sort_order": "asc",
                    "limit": 100000,
                },
                "json",
            ),
            tenor,
        )
