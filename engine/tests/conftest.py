import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.postgres import Base
import app.models  # noqa: F401 — register all models with Base


TEST_DATABASE_URL = settings.database_url.rsplit("/", 1)[0] + "/graphmentor_test"

test_engine = create_engine(TEST_DATABASE_URL)
TestSession = sessionmaker(bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables at start, drop at end."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db():
    """Provide a transactional session that rolls back after each test."""
    session = TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
