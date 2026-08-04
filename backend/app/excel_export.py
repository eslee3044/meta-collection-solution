from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Iterable

import xlsxwriter


SHEET_COLOR = "#4C6FFF"
HEADER_COLOR = "#15243A"
LIGHT_COLOR = "#EDF1FF"


def build_schema_workbook(payload: dict[str, Any], captured_at: datetime, fingerprint: str, selected_items: set[str] | None = None) -> bytes:
    selected = {"SUMMARY", "TABLE", "COLUMN", "VIEW", "INDEX", "FOREIGN KEY", "PROCEDURE", "SELECT PRIVILEGE", "STORAGE"} if selected_items is None else selected_items
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True, "constant_memory": False})
    workbook.set_properties({
        "title": f"{payload.get('source', 'MetaVault')} schema metadata",
        "subject": "Database schema metadata export",
        "author": "MetaVault",
        "company": "MetaVault",
    })

    formats = _formats(workbook)
    schemas = payload.get("schemas") or []
    tables = [(schema, table) for schema in schemas for table in schema.get("tables", [])]
    views = [(schema, view) for schema in schemas for view in schema.get("views", [])]

    if "SUMMARY" in selected:
        _summary_sheet(workbook, formats, payload, captured_at, fingerprint, schemas, tables, views)
    if "TABLE" in selected:
        _tables_sheet(workbook, formats, tables, include_storage="STORAGE" in selected)
    if "COLUMN" in selected:
        _columns_sheet(workbook, formats, tables)
    if "VIEW" in selected:
        _views_sheet(workbook, formats, views)
    if "INDEX" in selected:
        _indexes_sheet(workbook, formats, tables)
    if "FOREIGN KEY" in selected:
        _foreign_keys_sheet(workbook, formats, tables)
    if "PROCEDURE" in selected:
        _procedures_sheet(workbook, formats, schemas)
    if "SELECT PRIVILEGE" in selected:
        _permissions_sheet(workbook, formats, schemas)
    if "STORAGE" in selected:
        _storage_sheet(workbook, formats, tables)

    workbook.close()
    return output.getvalue()


def _formats(workbook: xlsxwriter.Workbook) -> dict[str, Any]:
    row_border = {"bottom": 1, "bottom_color": "#E8ECF2"}
    return {
        "title": workbook.add_format({"bold": True, "font_size": 18, "font_color": "#FFFFFF", "bg_color": HEADER_COLOR, "align": "left", "valign": "vcenter"}),
        "section": workbook.add_format({"bold": True, "font_size": 11, "font_color": "#FFFFFF", "bg_color": SHEET_COLOR, "valign": "vcenter"}),
        "label": workbook.add_format({"bold": True, "font_color": "#526075", "bg_color": LIGHT_COLOR}),
        "value": workbook.add_format({"font_color": "#27364D"}),
        "header": workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": HEADER_COLOR, "border": 0, "align": "center", "valign": "vcenter", "text_wrap": True}),
        "text": workbook.add_format({"font_color": "#334057", "valign": "top", "indent": 1, **row_border}),
        "wrap": workbook.add_format({"font_color": "#334057", "valign": "top", "text_wrap": True, "indent": 1, **row_border}),
        "number": workbook.add_format({"font_color": "#334057", "num_format": "#,##0_ ", "align": "right", **row_border}),
        "percent": workbook.add_format({"font_color": "#334057", "num_format": "0.00%_ ", "align": "right", **row_border}),
        "date": workbook.add_format({"font_color": "#334057", "num_format": "yyyy-mm-dd hh:mm:ss", **row_border}),
        "yes": workbook.add_format({"font_color": "#167A59", "bg_color": "#E9F8F2", "align": "center", **row_border}),
        "no": workbook.add_format({"font_color": "#758196", "align": "center", **row_border}),
    }


def _base_sheet(workbook: xlsxwriter.Workbook, name: str, headers: list[str], widths: list[int], formats: dict[str, Any]):
    sheet = workbook.add_worksheet(name)
    sheet.hide_gridlines(2)
    sheet.freeze_panes(1, 0)
    sheet.set_row(0, 30)
    for column, (header, width) in enumerate(zip(headers, widths)):
        sheet.write_string(0, column, header, formats["header"])
        sheet.set_column(column, column, width)
    return sheet


def _write_row(sheet, row: int, values: Iterable[Any], formats: dict[str, Any], percent_columns: set[int] | None = None, wrap_columns: set[int] | None = None):
    percent_columns = percent_columns or set()
    wrap_columns = wrap_columns or set()
    for column, value in enumerate(values):
        if value is None:
            sheet.write_blank(row, column, None, formats["text"])
        elif column in percent_columns and isinstance(value, (int, float)):
            sheet.write_number(row, column, value, formats["percent"])
        elif isinstance(value, bool):
            sheet.write_string(row, column, "YES" if value else "NO", formats["yes"] if value else formats["no"])
        elif isinstance(value, (int, float)):
            sheet.write_number(row, column, value, formats["number"])
        elif isinstance(value, datetime):
            sheet.write_datetime(row, column, value.replace(tzinfo=None), formats["date"])
        else:
            sheet.write_string(row, column, str(value), formats["wrap"] if column in wrap_columns else formats["text"])


def _finish_table(sheet, row_count: int, column_count: int):
    if row_count > 1:
        sheet.autofilter(0, 0, row_count - 1, column_count - 1)
        sheet.set_row(0, 30)


def _summary_sheet(workbook, formats, payload, captured_at, fingerprint, schemas, tables, views):
    sheet = workbook.add_worksheet("요약")
    sheet.hide_gridlines(2)
    sheet.set_column("A:A", 22)
    sheet.set_column("B:B", 48)
    sheet.set_column("C:D", 20)
    sheet.set_row(0, 36)
    sheet.merge_range("A1:D1", "MetaVault 스키마 메타데이터", formats["title"])
    sheet.merge_range("A3:D3", "수집 정보", formats["section"])
    info = [
        ("데이터 소스", payload.get("source")),
        ("DB 종류", payload.get("db_type")),
        ("데이터베이스", payload.get("database")),
        ("수집 시각", captured_at),
        ("Fingerprint", fingerprint),
        ("수집 옵션", "기본 + 스토리지 증가량" if payload.get("collection_options", {}).get("storage_growth") else "기본 메타데이터"),
    ]
    for row, (label, value) in enumerate(info, start=3):
        sheet.write_string(row, 0, label, formats["label"])
        if isinstance(value, datetime):
            sheet.write_datetime(row, 1, value.replace(tzinfo=None), formats["date"])
        else:
            sheet.merge_range(row, 1, row, 3, "" if value is None else str(value), formats["value"])

    start = 11
    sheet.merge_range(start, 0, start, 3, "객체 요약", formats["section"])
    columns = sum(len(table.get("columns", [])) for _, table in tables)
    indexes = sum(len(table.get("indexes", [])) for _, table in tables)
    foreign_keys = sum(len(table.get("foreign_keys", [])) for _, table in tables)
    metrics = [("스키마", len(schemas)), ("테이블", len(tables)), ("뷰", len(views)), ("컬럼", columns), ("인덱스", indexes), ("외래 키", foreign_keys)]
    for offset, (label, value) in enumerate(metrics, start=1):
        sheet.write_string(start + offset, 0, label, formats["label"])
        sheet.write_number(start + offset, 1, value, formats["number"])

    storage = payload.get("storage_summary")
    if storage:
        storage_start = start + len(metrics) + 2
        sheet.merge_range(storage_start, 0, storage_start, 3, "스토리지 요약 (Bytes)", formats["section"])
        storage_rows = [
            ("데이터", storage.get("data_bytes")), ("인덱스", storage.get("index_bytes")),
            ("전체", storage.get("total_bytes")), ("이전 대비 증가량", storage.get("growth_bytes")),
            ("관측 테이블", storage.get("observed_tables")), ("비교 가능 테이블", storage.get("comparable_tables")),
        ]
        for offset, (label, value) in enumerate(storage_rows, start=1):
            sheet.write_string(storage_start + offset, 0, label, formats["label"])
            if value is not None:
                sheet.write_number(storage_start + offset, 1, value, formats["number"])


def _tables_sheet(workbook, formats, tables, include_storage: bool = True):
    headers = ["스키마", "테이블", "설명", "컬럼 수", "기본 키", "외래 키 수", "인덱스 수"]
    widths = [20, 28, 38, 11, 24, 11, 11]
    if include_storage:
        headers += ["데이터 Bytes", "인덱스 Bytes", "전체 Bytes", "증가 Bytes", "증가율", "예상 행 수"]
        widths += [16, 16, 16, 16, 12, 16]
    sheet = _base_sheet(workbook, "테이블", headers, widths, formats)
    for row, (schema, table) in enumerate(tables, start=1):
        storage = table.get("storage") or {}
        values = [schema.get("name"), table.get("name"), table.get("comment"), len(table.get("columns", [])), ", ".join(table.get("primary_key", {}).get("constrained_columns") or []), len(table.get("foreign_keys", [])), len(table.get("indexes", []))]
        if include_storage:
            growth_percent = storage.get("growth_percent")
            values += [storage.get("data_bytes"), storage.get("index_bytes"), storage.get("total_bytes"), storage.get("growth_bytes"), growth_percent / 100 if growth_percent is not None else None, storage.get("row_estimate")]
        _write_row(sheet, row, values, formats, percent_columns={11} if include_storage else set(), wrap_columns={2})
    _finish_table(sheet, len(tables) + 1, len(headers))


def _columns_sheet(workbook, formats, tables):
    headers = ["스키마", "테이블", "순번", "컬럼", "데이터 타입", "NULL 허용", "기본값", "설명", "기본 키"]
    sheet = _base_sheet(workbook, "컬럼", headers, [20, 28, 9, 28, 24, 12, 30, 40, 11], formats)
    row = 1
    for schema, table in tables:
        primary_keys = set(table.get("primary_key", {}).get("constrained_columns") or [])
        for ordinal, column in enumerate(table.get("columns", []), start=1):
            values = [schema.get("name"), table.get("name"), ordinal, column.get("name"), column.get("type"), bool(column.get("nullable")), column.get("default"), column.get("comment"), column.get("name") in primary_keys]
            _write_row(sheet, row, values, formats, wrap_columns={6, 7})
            row += 1
    _finish_table(sheet, row, len(headers))


def _views_sheet(workbook, formats, views):
    headers = ["스키마", "뷰", "정의"]
    sheet = _base_sheet(workbook, "뷰", headers, [20, 30, 100], formats)
    for row, (schema, view) in enumerate(views, start=1):
        definition = str(view.get("definition") or "")
        _write_row(sheet, row, [schema.get("name"), view.get("name"), definition], formats, wrap_columns={2})
        sheet.set_row(row, min(300, max(42, 18 * (definition.count("\n") + 2))))
    _finish_table(sheet, len(views) + 1, len(headers))


def _indexes_sheet(workbook, formats, tables):
    headers = ["스키마", "테이블", "인덱스", "컬럼", "고유"]
    sheet = _base_sheet(workbook, "인덱스", headers, [20, 28, 32, 50, 10], formats)
    row = 1
    for schema, table in tables:
        for index in table.get("indexes", []):
            _write_row(sheet, row, [schema.get("name"), table.get("name"), index.get("name"), ", ".join(index.get("column_names") or []), bool(index.get("unique"))], formats)
            row += 1
    _finish_table(sheet, row, len(headers))


def _foreign_keys_sheet(workbook, formats, tables):
    headers = ["스키마", "테이블", "외래 키", "로컬 컬럼", "참조 스키마", "참조 테이블", "참조 컬럼"]
    sheet = _base_sheet(workbook, "외래 키", headers, [20, 28, 32, 40, 20, 28, 40], formats)
    row = 1
    for schema, table in tables:
        for key in table.get("foreign_keys", []):
            _write_row(sheet, row, [schema.get("name"), table.get("name"), key.get("name"), ", ".join(key.get("constrained_columns") or []), key.get("referred_schema"), key.get("referred_table"), ", ".join(key.get("referred_columns") or [])], formats)
            row += 1
    _finish_table(sheet, row, len(headers))


def _procedures_sheet(workbook, formats, schemas):
    headers = ["스키마", "프로시저/함수", "유형", "정의"]
    sheet = _base_sheet(workbook, "프로시저", headers, [20, 34, 18, 100], formats)
    row = 1
    for schema in schemas:
        for procedure in schema.get("procedures", []):
            _write_row(sheet, row, [schema.get("name"), procedure.get("name"), procedure.get("routine_type") or procedure.get("type"), procedure.get("definition") or procedure.get("body")], formats, wrap_columns={3})
            row += 1
    _finish_table(sheet, row, len(headers))


def _permissions_sheet(workbook, formats, schemas):
    headers = ["스키마", "객체 유형", "객체", "SELECT 가능", "확인 사용자", "권한 목록"]
    sheet = _base_sheet(workbook, "조회 권한", headers, [20, 16, 34, 14, 24, 60], formats)
    row = 1
    for schema in schemas:
        for object_type, objects in (("테이블", schema.get("tables", [])), ("뷰", schema.get("views", []))):
            for item in objects:
                permission = item.get("permissions") or {}
                _write_row(sheet, row, [schema.get("name"), object_type, item.get("name"), permission.get("select"), permission.get("checked_as"), ", ".join(permission.get("privileges") or [])], formats, wrap_columns={5})
                row += 1
    _finish_table(sheet, row, len(headers))


def _storage_sheet(workbook, formats, tables):
    headers = ["스키마", "테이블", "데이터 Bytes", "인덱스 Bytes", "전체 Bytes", "이전 전체 Bytes", "증가 Bytes", "증가율", "예상 행 수"]
    sheet = _base_sheet(workbook, "스토리지", headers, [20, 28, 18, 18, 18, 20, 16, 12, 16], formats)
    for row, (schema, table) in enumerate(tables, start=1):
        storage = table.get("storage") or {}
        growth_percent = storage.get("growth_percent")
        values = [schema.get("name"), table.get("name"), storage.get("data_bytes"), storage.get("index_bytes"), storage.get("total_bytes"), storage.get("previous_total_bytes"), storage.get("growth_bytes"), growth_percent / 100 if growth_percent is not None else None, storage.get("row_estimate")]
        _write_row(sheet, row, values, formats, percent_columns={7})
    _finish_table(sheet, len(tables) + 1, len(headers))
