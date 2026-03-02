import pytest
from sqlalchemy import create_engine, event
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
    """Provide a transactional session that rolls back after each test.

    Uses a nested transaction (SAVEPOINT) so that db.commit() calls inside
    endpoints only commit the savepoint, not the outer transaction. The outer
    transaction is always rolled back at teardown, keeping test isolation.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSession(bind=connection)

    # Begin a nested transaction (SAVEPOINT)
    session.begin_nested()

    # When the endpoint calls session.commit(), SQLAlchemy ends the SAVEPOINT.
    # We need to re-open a new SAVEPOINT so subsequent operations still work.
    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess, trans):
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
