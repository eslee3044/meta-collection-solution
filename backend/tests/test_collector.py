from pathlib import Path

from sqlalchemy import create_engine, text

from app.collector import collect_schema
from app.models import DataSource


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

