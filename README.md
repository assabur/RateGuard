# RateGuard

A Python platform for monitoring US interest rates and reconciling **U.S. Treasury** and **FRED** data across **2Y / 5Y / 10Y / 30Y** maturities. An independent project focused on the quality and traceability of data used in quantitative research.

## Local setup

Python **3.11+** and **PostgreSQL** are required, including for the demo. Docker Compose can start the local database. An existing PostgreSQL instance also works.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# Edit .env: use the same password in RATE_GUARD_POSTGRES_PASSWORD
# and RATE_GUARD_DATABASE_URL (with the postgresql+psycopg:// prefix).
docker compose up -d postgres
# Wait until the service is healthy: docker compose ps
rateguard demo
rateguard serve
```

Open **http://127.0.0.1:8000/** for the dashboard and **http://127.0.0.1:8000/docs** to query the API. The demo uses **synthetic data dated January 8, 2025**; data endpoints explicitly require `?mode=demo`. By default, they query only live ingestion runs and return 404 if none exist.

The dashboard lets you select **Collectes réelles / Démonstration synthétique** (live ingestion runs / synthetic demo), filter by date, and inspect a specific run among the latest 30 in the selected mode. It displays Treasury/FRED curves, differences in bps, spreads, anomalies, and current data freshness. After running `rateguard demo`, select **Démonstration synthétique**. Leaving the date blank selects the latest available report. Invalid points are excluded from the chart; their values and statuses remain available in the table.

The HTML/CSS/JavaScript interface is served by FastAPI, with no build step or CDN. It queries the API on the same origin and requires no additional web service.

```bash
curl 'http://127.0.0.1:8000/reconciliation?mode=demo'
curl 'http://127.0.0.1:8000/curves?mode=demo'
```

The demo uses the same parsers and storage as live ingestion. Its results include:

| Maturity | Treasury | FRED | Difference | Status |
| --- | ---: | ---: | ---: | --- |
| 2Y | 4.80% | 4.80% | 0 bp | OK |
| 5Y | 4.95% | 4.92% | 3 bps | WARNING |
| 10Y | 5.15% | 5.13% | 2 bps | OK |
| 30Y | 5.35% | 5.28% | 7 bps | CRITICAL |

The overall demo status is therefore **CRITICAL**. Synthetic data is never marked as usable for research.

## Collecting live data

Create a [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html), then set `FRED_API_KEY` in `.env`. Treasury requires no key.

```bash
rateguard ingest --as-of 2025-01-08
# Without --as-of: today's date in New York.
rateguard ingest
```

Choose a publication date. A date with no observation, a public holiday, or ingestion before publication produces a CRITICAL status; values are never carried forward from the previous day. You can rerun ingestion after publication: runs are stored separately. A change in the same value between two runs for the same observation date is flagged as an observed revision, without asserting its cause.

The command returns a JSON report. It exits with code **1** if the live result is CRITICAL, or **0** for OK/WARNING. A missing key causes failure before any data is collected. A provider outage produces a CRITICAL report containing the other available data.

## Business rules

- Yields are expressed as **percentages**: `5.15` means `5.15%`. `abs(Treasury - FRED) × 100` gives the difference in **bps**. Decimal arithmetic prevents floating-point errors from incorrectly classifying a 2 bps difference as exceeding the threshold.
- Reconciliation uses the **observation date + maturity** key. OK if the difference is ≤ 2 bps; WARNING if 2 < difference ≤ 5 bps; CRITICAL above that. Thresholds are configurable in `.env`.
- A missing, nonnumeric, nonfinite, out-of-range (outside `[-5, 25]%`), or duplicate value is CRITICAL and excluded from calculations. Any missing value on the requested date is CRITICAL. The maximum age is 4 calendar days, configurable. A movement > 100 bps between two valid observations triggers WARNING.
- Descriptive curves contain four points; spreads are `5Y-2Y`, `10Y-2Y`, `10Y-5Y`, `30Y-10Y`, and `30Y-2Y`. Classification is based on **10Y-2Y**: NORMAL > 5 bps, FLAT within `[-5, 5]`, INVERTED < -5. `has_local_inversion` separately indicates inversions between adjacent points. No zero-coupon curve bootstrapping is performed.
- Data quality can worsen the reconciliation status. An incomplete curve produces no spreads. The overall status is the most severe of the four reconciliations and becomes CRITICAL if ingestion fails.
- `usable_as_of` follows a conservative technical policy: only a live ingestion run with an entirely OK status is eligible. A WARNING requires review. Each maturity also exposes its own eligibility. When the API is queried, `usable_today` additionally checks the report's age; a historical OK report does not mean the data is current.

**Interpreting the providers:** FRED distributes the Federal Reserve's constant-maturity DGS yield series (H.15), expressed as daily percentages. Treasury publishes par yields from its official curve. These are not two independent providers of executable prices. Differences may reflect publication dates, rounding, conventions, or revisions; the thresholds are a demonstration policy to be calibrated with domain experts. [DGS10 series](https://fred.stlouisfed.org/series/DGS10), [Treasury yields](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve).

## Storage and audit

```text
src/rateguard/
  providers.py   # HTTP clients, bounded retries, XML/JSON parsers
  analytics.py   # Quality, reconciliation, curves
  pipeline.py    # Ingestion → normalization → checks → storage
  storage.py     # SQLAlchemy, PostgreSQL, run history
  api.py         # Read-only FastAPI application
  cli.py         # demo / ingest / serve
  demo.py        # Deterministic synthetic sources

data/
  {live,demo}/runs/<run_id>/
    raw/                     # Source responses + SHA-256 / UTC metadata
    observations.parquet     # Normalized observations, duplicates retained for audit
    reconciliation.parquet
    report.json
```

Each run creates a UUID, preserves provenance for each observation, and retains FRED's `realtime_start/end` fields. Secrets and URLs containing the API key are not recorded. The observation date and UTC ingestion timestamp are distinct; provider publication times are not fabricated.

PostgreSQL is the only database engine used by the application. `RATE_GUARD_DATABASE_URL=postgresql+psycopg://...` is required; missing configuration or SQLite is explicitly rejected. Reports and observations are inserted in a single SQL transaction. Files are written before the commit; a SQL failure may leave an orphaned directory that does not appear in the API. Runs are immutable snapshots: rerunning a date does not delete earlier versions, and the API selects the latest run for that date. Without a date, it first selects the most recent observation date.

## API

| GET endpoint | Result |
| --- | --- |
| `/health` | Database connectivity; does not certify data quality |
| `/report?as_of=2025-01-08` | Complete report and freshness at query time |
| `/reconciliation` | Comparison across the four maturities |
| `/curves` | Points, spreads, and classification by provider |
| `/quality` | Checks, anomalies, and ingestion errors |
| `/runs?limit=30` | History, up to 365 runs |
| `/runs/{run_id}` | Specific snapshot and current freshness |

All data endpoints except `/runs/{run_id}` accept `mode=live` (default) or `mode=demo`. The API is local, read-only, and unauthenticated; it is not intended for direct public exposure.

## Running the full application with Docker

In `.env`, set `RATE_GUARD_POSTGRES_PASSWORD` to a local alphanumeric password. Stop the local API to free port 8000 if necessary.

```bash
docker compose up -d --build
docker compose run --rm api rateguard demo
docker compose run --rm api rateguard ingest --as-of 2025-01-08
docker compose down
```

Volumes preserve the database and files. Ingestion and the API must use the same `RATE_GUARD_DATA_DIR` and database. The PostgreSQL and API services listen only on localhost.

## Verification

```bash
docker compose up -d postgres
# A dedicated database is recommended; tests create and drop their own schemas.
# Do not use a production database. Copy a test database URL into this variable.
export RATE_GUARD_TEST_DATABASE_URL='postgresql+psycopg://rateguard:YOUR_PASSWORD@127.0.0.1:5432/rateguard'
make test
make lint
```

Tests use mocked HTTP responses and isolated temporary PostgreSQL schemas. Without `RATE_GUARD_TEST_DATABASE_URL`, integration tests are marked as skipped; business logic tests can still run. CI starts PostgreSQL 17 and configures this variable to run the full suite. Tests check bps boundaries, missing data, duplicates, invalid values, provider outages, revisions, freshness, and demo/live separation. CI is configured for Python 3.11 and 3.13. Completed checks and their limitations are documented in [docs/validation.md](docs/validation.md).

## Next steps

See [PLAN.md](PLAN.md) for the roadmap: a US publication calendar and provider SLAs, Grafana metrics, Airflow orchestration, then EUR data from the ECB. These integrations are not part of the delivered MVP.

Technical sources: [Treasury XML](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed), [FRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html).
