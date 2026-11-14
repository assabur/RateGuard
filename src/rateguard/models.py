from dataclasses import asdict, dataclass
from datetime import date, datetime

TENORS = (2, 5, 10, 30)
PROVIDERS = ("treasury", "fred")
SERIES = {tenor: f"DGS{tenor}" for tenor in TENORS}
RANK = {"OK": 0, "WARNING": 1, "CRITICAL": 2}


def worst(statuses):
    return max(statuses, key=RANK.__getitem__, default="OK")


@dataclass(frozen=True)
class Observation:
    provider: str
    observation_date: date
    tenor_years: int
    yield_pct: float | None
    retrieved_at: datetime
    source_id: str
    raw_file: str
    realtime_start: str | None = None
    realtime_end: str | None = None
    parse_issue: str | None = None

    def record(self):
        row = asdict(self)
        row["observation_date"] = self.observation_date.isoformat()
        row["retrieved_at"] = self.retrieved_at.isoformat()
        return row
