import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.database import Base, get_db
from app.main import app


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
def engine(tmp_path):
    """A fresh file-backed SQLite database per test, with foreign keys enforced
    exactly like the real engine (see app/database.py)."""
    db_file = tmp_path / "test.db"
    eng = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    event.listen(eng, "connect", _enable_sqlite_foreign_keys)
    Base.metadata.create_all(eng)
    # Seed the two warehouses the app seeds on startup (ids 1 and 2).
    with Session(eng) as session, session.begin():
        session.add_all(
            [
                models.Warehouse(name="Paris warehouse"),
                models.Warehouse(name="Lyon warehouse"),
            ]
        )
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine):
    """A TestClient whose get_db dependency is pointed at the test database.

    Not used as a context manager on purpose, so the app's lifespan (which would
    create/seed the real stock.db) never runs during tests.
    """
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        with TestingSessionLocal() as session, session.begin():
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def db(engine):
    """Direct read access to the same database, for asserting on rows."""
    with Session(engine) as session:
        yield session


@pytest.fixture
def make_product(client):
    """Factory: create a product via the API and return its id."""

    def _make(sku="WIDGET-1", name="Widget", unit_price=9.99, reorder_threshold=0):
        resp = client.post(
            "/products",
            json={
                "sku": sku,
                "name": name,
                "unit_price": unit_price,
                "reorder_threshold": reorder_threshold,
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    return _make
