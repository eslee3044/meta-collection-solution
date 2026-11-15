from sqlalchemy import Integer

from app.main import _snapshot_objects
from app.models import MetaTableExt


def test_snapshot_objects_includes_views_with_object_type():
    payload = {
        "schemas": [
            {
                "name": "public",
                "tables": [{"name": "orders", "columns": []}],
                "views": [{"name": "order_summary", "columns": [{"name": "order_id"}], "definition": "SELECT 1"}],
            }
        ]
    }

    objects = _snapshot_objects(payload)

    assert objects["orders"][2] == "TABLE"
    assert objects["order_summary"][2] == "VIEW"
    assert objects["order_summary"][1]["definition"] == "SELECT 1"


def test_legacy_pk_duplicate_column_is_integer():
    assert isinstance(MetaTableExt.__table__.c.sql_tgt_pk_dup.type, Integer)
