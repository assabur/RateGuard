import pytest

from rateguard.config import Settings


def test_database_configuration_is_required():
    with pytest.raises(ValueError, match="RATE_GUARD_DATABASE_URL"):
        Settings()


@pytest.mark.parametrize("url", ["sqlite:///market.db", "mysql://localhost/db", "invalid"])
def test_other_database_backends_are_rejected(url):
    with pytest.raises(ValueError, match="PostgreSQL|postgresql"):
        Settings(database_url=url)
