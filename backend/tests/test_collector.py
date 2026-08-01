from pathlib import Path

from sqlalchemy import create_engine, text

from app.collector import collect_schema
from app.models import DataSource
from app.scheduler import apply_storage_growth


def test_sqlite_schema_collection(tmp_path: Path):
    db_path = tmp_path / "sample.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)"))
        connection.execute(text("CREATE TABLE members (id INTEGER PRIMARY KEY, team_id INTEGER REFERENCES teams(id), email TEXT)"))
        connection.execute(text("CREATE INDEX ix_members_email ON members(email)"))

    source = DataSource(name="sample", db_type="sqlite", database=str(db_path), host="", username="")
    payload, count, fingerprint = collect_schema(source)

    assert count == 2
    assert len(fingerprint) == 64
    tables = {table["name"]: table for schema in payload["schemas"] for table in schema["tables"]}
    assert set(tables) == {"teams", "members"}
    assert any(fk["referred_table"] == "teams" for fk in tables["members"]["foreign_keys"])


def test_sqlite_storage_and_growth_collection(tmp_path: Path):
    db_path = tmp_path / "storage.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE events (id INTEGER PRIMARY KEY, payload TEXT)"))
        connection.execute(text("CREATE INDEX ix_events_payload ON events(payload)"))
        connection.execute(text("INSERT INTO events(payload) VALUES ('first'), ('second')"))

    source = DataSource(name="storage", db_type="sqlite", database=str(db_path), host="", username="")
    baseline, _, _ = collect_schema(source, include_storage=True)
    apply_storage_growth(baseline, None)
    table = baseline["schemas"][0]["tables"][0]
    assert table["storage"]["total_bytes"] > 0
    assert baseline["storage_summary"]["observed_tables"] == 1
    assert baseline["storage_summary"]["comparable_tables"] == 0

    current, _, _ = collect_schema(source, include_storage=True)
    apply_storage_growth(current, baseline)
    storage = current["schemas"][0]["tables"][0]["storage"]
    assert storage["growth_bytes"] == 0
    assert current["storage_summary"]["comparable_tables"] == 1
