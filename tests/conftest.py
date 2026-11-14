from datetime import UTC, date, datetime

import pytest

from rateguard.config import Settings
from rateguard.models import PROVIDERS, TENORS, Observation

DAY = date(2025, 1, 8)
NOW = datetime(2025, 1, 9, 12, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "data",
        database_url="postgresql+psycopg://rateguard:test@127.0.0.1/rateguard",
        fred_api_key="test-secret",
    )


@pytest.fixture
def observations():
    return [
        Observation(provider, DAY, tenor, value, NOW, f"{provider}-{tenor}", "raw/source")
        for provider in PROVIDERS
        for tenor, value in zip(TENORS, (4.8, 4.95, 5.15, 5.35), strict=True)
    ]


@pytest.fixture
def postgres_settings(settings):
    import os
    from dataclasses import replace
    from uuid import uuid4

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    database_url = os.getenv("RATE_GUARD_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set RATE_GUARD_TEST_DATABASE_URL to run PostgreSQL integration tests")
    schema = "test_" + uuid4().hex
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(database_url).update_query_dict({"options": f"-csearch_path={schema}"})
    try:
        yield replace(settings, database_url=url.render_as_string(hide_password=False))
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
