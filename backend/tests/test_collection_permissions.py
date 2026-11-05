from app.catalog.collection_permissions import check_collection_catalog_permissions
from app.models import CollectionJob, DataSource


def test_catalog_permission_check_lists_required_information_schema_objects(monkeypatch):
    class Connection:
        def execute(self, statement):
            text = str(statement)
            if "COLUMNS" in text:
                raise RuntimeError("permission denied")
            return []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Engine:
        def connect(self):
            return Connection()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.catalog.collection_permissions.source_engine", lambda source: Engine())
    source = DataSource(name="mysql", db_type="mysql", database="app", host="db", username="reader")
    job = CollectionJob(name="daily", data_source_id=1, schemas=["app"], collection_items=["TABLE", "COLUMN", "PROCEDURE"])

    result = check_collection_catalog_permissions(source, job)

    objects = {item["object_name"]: item for item in result["requirements"]}
    assert "information_schema.TABLES" in objects
    assert "information_schema.COLUMNS" in objects
    assert "information_schema.ROUTINES" in objects
    assert objects["information_schema.TABLES"]["status"] == "allowed"
    assert objects["information_schema.COLUMNS"]["status"] == "denied"
    assert result["summary"]["denied"] == 1


def test_bigquery_catalog_permission_is_explicitly_unknown(monkeypatch):
    class Engine:
        def connect(self):
            raise AssertionError("BigQuery IAM must not be guessed with a generic SQL probe")

    monkeypatch.setattr("app.catalog.collection_permissions.source_engine", lambda source: Engine())
    source = DataSource(name="bq", db_type="bigquery", database="project", host="", username="reader")
    job = CollectionJob(name="daily", data_source_id=1, schemas=["dataset"], collection_items=["TABLE", "COLUMN", "PROCEDURE"])

    result = check_collection_catalog_permissions(source, job)

    assert result["status"] == "partial"
    assert all(item["status"] == "unknown" for item in result["requirements"])
