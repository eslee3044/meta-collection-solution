from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile

from app.excel_export import build_schema_workbook


def test_schema_workbook_contains_expected_sheets_and_safe_text():
    payload = {
        "source": "Sample DB",
        "db_type": "sqlite",
        "database": "sample.db",
        "collection_options": {"basic": True, "storage_growth": True},
        "storage_summary": {"data_bytes": 4096, "index_bytes": 1024, "total_bytes": 5120, "growth_bytes": 128, "observed_tables": 1, "comparable_tables": 1},
        "schemas": [{
            "name": "main",
            "tables": [{
                "name": "customers", "comment": "=HYPERLINK(\"https://example.com\")", "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "default": None, "comment": "identifier"},
                    {"name": "email", "type": "TEXT", "nullable": True, "default": None, "comment": None},
                ],
                "primary_key": {"constrained_columns": ["id"]},
                "foreign_keys": [],
                "indexes": [{"name": "ix_customers_email", "column_names": ["email"], "unique": True}],
                "storage": {"data_bytes": 4096, "index_bytes": 1024, "total_bytes": 5120, "growth_bytes": 128, "growth_percent": 2.5, "row_estimate": 10},
            }],
            "views": [{"name": "customer_view", "definition": "SELECT id, email FROM customers"}],
        }],
    }
    content = build_schema_workbook(payload, datetime(2026, 8, 1, tzinfo=timezone.utc), "a" * 64)

    assert content.startswith(b"PK")
    with ZipFile(BytesIO(content)) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode()
        assert all(name in workbook_xml for name in ["요약", "테이블", "컬럼", "뷰", "인덱스", "외래 키"])
        worksheet_xml = b"".join(archive.read(name) for name in archive.namelist() if name.startswith("xl/worksheets/sheet"))
        assert b"<f>" not in worksheet_xml
