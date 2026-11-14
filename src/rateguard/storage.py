"""Append-only run snapshots stored in PostgreSQL."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
)

from .config import Settings

metadata = MetaData()
runs = Table(
    "market_runs",
    metadata,
    Column("run_id", String(36), primary_key=True),
    Column("as_of", Date, nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("mode", String(8), nullable=False, index=True),
    Column("status", String(12), nullable=False),
    Column("report", JSON, nullable=False),
)
observations = Table(
    "market_observations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(36), ForeignKey("market_runs.run_id"), nullable=False, index=True),
    Column("provider", String(16), nullable=False),
    Column("observation_date", Date, nullable=False),
    Column("tenor_years", Integer, nullable=False),
    Column("yield_pct", Float),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("source_id", String(32), nullable=False),
    Column("raw_file", String, nullable=False),
    Column("realtime_start", String(10)),
    Column("realtime_end", String(10)),
    Column("parse_issue", String(32)),
)


class Repository:
    def __init__(self, settings: Settings):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 10}
        )
        metadata.create_all(self.engine)

    def save(self, report, rows):
        with self.engine.begin() as conn:
            conn.execute(
                insert(runs),
                {
                    "run_id": report["run_id"],
                    "as_of": date.fromisoformat(report["as_of"]),
                    "created_at": datetime.fromisoformat(report["created_at"]),
                    "mode": report["mode"],
                    "status": report["status"],
                    "report": report,
                },
            )
            if rows:
                conn.execute(
                    insert(observations),
                    [{"run_id": report["run_id"], **row.__dict__} for row in rows],
                )

    def latest(self, as_of=None, mode="live"):
        query = select(runs.c.report).where(runs.c.mode == mode)
        if as_of:
            query = query.where(runs.c.as_of == as_of)
        query = query.order_by(runs.c.as_of.desc(), runs.c.created_at.desc(), runs.c.run_id.desc())
        with self.engine.connect() as conn:
            return conn.execute(query.limit(1)).scalar_one_or_none()

    def by_id(self, run_id):
        with self.engine.connect() as conn:
            return conn.execute(
                select(runs.c.report).where(runs.c.run_id == run_id)
            ).scalar_one_or_none()

    def history(self, mode="live", limit=30):
        query = (
            select(
                runs.c.run_id,
                runs.c.as_of,
                runs.c.created_at,
                runs.c.mode,
                runs.c.status,
            )
            .where(runs.c.mode == mode)
            .order_by(runs.c.as_of.desc(), runs.c.created_at.desc())
            .limit(limit)
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(query).mappings()]

    def close(self):
        self.engine.dispose()
