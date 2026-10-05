from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./stock.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)


# SQLite ignores foreign-key constraints unless they are explicitly enabled,
# and the pragma must be set on every new connection (hence this connect
# listener rather than a one-off call). Without it, the ForeignKey declarations
# in models.py are decorative and orphan rows can be written. A production
# database such as Postgres enforces foreign keys natively.
@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as session, session.begin():
        yield session
