import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    database_url: str | None = None
    fred_api_key: str = ""
    ok_bps: float = 2.0
    warning_bps: float = 5.0
    flat_bps: float = 5.0
    max_age_days: int = 4
    jump_bps: float = 100.0

    def __post_init__(self):
        if not self.database_url:
            raise ValueError("Configure RATE_GUARD_DATABASE_URL with a PostgreSQL connection URL")
        try:
            url = make_url(self.database_url)
        except Exception:
            raise ValueError("RATE_GUARD_DATABASE_URL must be a valid PostgreSQL URL") from None
        if url.drivername != "postgresql+psycopg":
            raise ValueError("RATE_GUARD_DATABASE_URL must use postgresql+psycopg://")
        numbers = (self.ok_bps, self.warning_bps, self.flat_bps, self.jump_bps)
        if not all(math.isfinite(x) for x in numbers):
            raise ValueError("Thresholds must be finite")
        if not 0 <= self.ok_bps < self.warning_bps:
            raise ValueError("Require 0 <= RATE_GUARD_OK_BPS < RATE_GUARD_WARNING_BPS")
        if self.flat_bps < 0 or self.max_age_days < 0 or self.jump_bps <= 0:
            raise ValueError("Invalid quality thresholds")

    @classmethod
    def from_env(cls):
        load_dotenv(override=False)
        return cls(
            data_dir=Path(os.getenv("RATE_GUARD_DATA_DIR", "data")),
            database_url=os.getenv("RATE_GUARD_DATABASE_URL") or None,
            fred_api_key=os.getenv("FRED_API_KEY", ""),
            ok_bps=float(os.getenv("RATE_GUARD_OK_BPS", "2")),
            warning_bps=float(os.getenv("RATE_GUARD_WARNING_BPS", "5")),
            flat_bps=float(os.getenv("RATE_GUARD_FLAT_BPS", "5")),
            max_age_days=int(os.getenv("RATE_GUARD_MAX_AGE_DAYS", "4")),
            jump_bps=float(os.getenv("RATE_GUARD_JUMP_BPS", "100")),
        )
