from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile

from app.excel_export import build_schema_workbook


def test_workbook_handles_null_index_and_key_columns():
    payload = {
        "source": "test",
        "schemas": [
            {
                "name": "public",
                "tables": [
                    {
                        "name": "events",
                        "columns": [],
                        "primary_key": {"constrained_columns": [None, "event_id"]},
                        "indexes": [{"name": "ix_events", "column_names": [None, "event_id"], "unique": False}],
                        "foreign_keys": [{"name": "fk_events", "constrained_columns": [None], "referred_columns": [None]}],
                    }
                ],
                "views": [],
                "procedures": [],
            }
        ],
    }

    content = build_schema_workbook(
        payload,
        datetime.now(timezone.utc),
        "fingerprint",
        selected_items={"TABLE", "INDEX", "FOREIGN KEY"},
    )

    assert content.startswith(b"PK")
    with ZipFile(BytesIO(content)) as workbook:
        assert "xl/workbook.xml" in workbook.namelist()
