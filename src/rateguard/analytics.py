"""Explicit quality policy, same-date reconciliation and descriptive par curves."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from .config import Settings
from .models import PROVIDERS, TENORS, Observation, worst


def bps(left: float, right: float) -> float:
    return float((Decimal(str(left)) - Decimal(str(right))) * 100)


def issue(code, status, detail):
    return {"code": code, "status": status, "detail": detail}


def evaluate(rows: list[Observation], as_of: date, settings: Settings, previous=None):
    groups = defaultdict(list)
    for row in rows:
        groups[(row.provider, row.tenor_years, row.observation_date)].append(row)
    quality = []
    points = []
    prior_points = {
        (p["provider"], p["tenor_years"]): p for p in (previous or {}).get("points", [])
    }
    for provider in PROVIDERS:
        for tenor in TENORS:
            history = sorted(
                [
                    (day, values)
                    for (p, t, day), values in groups.items()
                    if p == provider and t == tenor and day <= as_of
                ],
                key=lambda item: item[0],
            )
            previous_valid = None
            current = None
            last_valid_date = None
            for day, values in history:
                problems = []
                row = values[0]
                if len(values) != 1:
                    problems.append(issue("duplicate", "CRITICAL", f"{len(values)} rows for key"))
                if row.parse_issue or row.yield_pct is None:
                    problems.append(
                        issue(
                            row.parse_issue or "missing_value",
                            "CRITICAL",
                            "Yield is unavailable",
                        )
                    )
                elif not -5 <= row.yield_pct <= 25:
                    problems.append(issue("out_of_range", "CRITICAL", "Yield outside [-5, 25]%"))
                if not any(p["status"] == "CRITICAL" for p in problems):
                    if (
                        previous_valid
                        and abs(bps(row.yield_pct, previous_valid.yield_pct)) > settings.jump_bps
                    ):
                        problems.append(
                            issue(
                                "daily_jump",
                                "WARNING",
                                f"Change exceeds {settings.jump_bps} bps since "
                                f"{previous_valid.observation_date}",
                            )
                        )
                    previous_valid = row
                    last_valid_date = day
                quality.append(
                    {
                        "provider": provider,
                        "tenor_years": tenor,
                        "observation_date": day.isoformat(),
                        "status": worst(p["status"] for p in problems),
                        "issues": problems,
                    }
                )
                if day == as_of:
                    current = (row, problems)
            if current:
                row, problems = current
                problems = list(problems)
                value = row.yield_pct
                prior = prior_points.get((provider, tenor))
                if (
                    prior
                    and prior["yield_pct"] is not None
                    and value is not None
                    and bps(value, prior["yield_pct"]) != 0
                ):
                    problems.append(
                        issue(
                            "observed_revision",
                            "WARNING",
                            f"Previous run had {prior['yield_pct']}%; now {value}%. "
                            "Investigate source revision or ingestion change.",
                        )
                    )
                provenance = {
                    "retrieved_at": row.retrieved_at.isoformat(),
                    "raw_file": row.raw_file,
                    "source_id": row.source_id,
                    "realtime_start": row.realtime_start,
                    "realtime_end": row.realtime_end,
                }
            else:
                value = None
                provenance = None
                problems = [issue("missing_date", "CRITICAL", f"No observation for {as_of}")]
            age = (as_of - last_valid_date).days if last_valid_date else None
            if age is None or age > settings.max_age_days:
                problems.append(
                    issue(
                        "stale",
                        "CRITICAL",
                        f"Latest valid observation: {last_valid_date}",
                    )
                )
            points.append(
                {
                    "provider": provider,
                    "tenor_years": tenor,
                    "observation_date": str(as_of),
                    "yield_pct": value,
                    "last_valid_date": str(last_valid_date) if last_valid_date else None,
                    "age_days_as_of": age,
                    "status": worst(p["status"] for p in problems),
                    "issues": problems,
                    "provenance": provenance,
                }
            )
    reconciliations = []
    for tenor in TENORS:
        treasury, fred = [
            next(p for p in points if p["provider"] == provider and p["tenor_years"] == tenor)
            for provider in PROVIDERS
        ]
        usable_values = all(p["status"] != "CRITICAL" for p in (treasury, fred))
        delta = abs(bps(treasury["yield_pct"], fred["yield_pct"])) if usable_values else None
        difference_status = (
            "CRITICAL"
            if delta is None or delta > settings.warning_bps
            else "WARNING"
            if delta > settings.ok_bps
            else "OK"
        )
        status = worst([treasury["status"], fred["status"], difference_status])
        investigations = []
        if status != "OK":
            investigations = [
                "Verify observation dates, provider publication delays and ingestion timestamps.",
                "Check percent units, constant-maturity/par conventions and H.15 methodology.",
                "Compare archived responses and FRED realtime fields for revisions.",
            ]
        reconciliations.append(
            {
                "tenor_years": tenor,
                "observation_date": str(as_of),
                "treasury_pct": treasury["yield_pct"],
                "fred_pct": fred["yield_pct"],
                "absolute_difference_bps": delta,
                "difference_status": difference_status,
                "status": status,
                "quality_issues": {
                    "treasury": treasury["issues"],
                    "fred": fred["issues"],
                },
                "investigation": investigations,
            }
        )
    curves = []
    for provider in PROVIDERS:
        selected = [p for p in points if p["provider"] == provider]
        complete = all(p["status"] != "CRITICAL" for p in selected)
        values = {p["tenor_years"]: p["yield_pct"] for p in selected}
        spreads = {}
        shape = "INCOMPLETE"
        local_inversion = None
        if complete:
            spreads = {
                f"{long}Y-{short}Y": bps(values[long], values[short])
                for short, long in [(2, 5), (2, 10), (5, 10), (10, 30), (2, 30)]
            }
            slope = spreads["10Y-2Y"]
            shape = (
                "NORMAL"
                if slope > settings.flat_bps
                else "INVERTED"
                if slope < -settings.flat_bps
                else "FLAT"
            )
            local_inversion = any(spreads[key] < 0 for key in ("5Y-2Y", "10Y-5Y", "30Y-10Y"))
        curves.append(
            {
                "provider": provider,
                "observation_date": str(as_of),
                "shape": shape,
                "classification_basis": "10Y-2Y",
                "flat_threshold_bps": settings.flat_bps,
                "has_local_inversion": local_inversion,
                "spreads_bps": spreads,
                "status": worst(p["status"] for p in selected),
                "points": [
                    {"tenor_years": p["tenor_years"], "yield_pct": p["yield_pct"]} for p in selected
                ],
            }
        )
    return {
        "points": points,
        "quality": quality,
        "reconciliation": reconciliations,
        "curves": curves,
        "status": worst(r["status"] for r in reconciliations),
    }
