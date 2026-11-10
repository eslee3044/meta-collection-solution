from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, select
from sqlalchemy.engine import Connection

from .collector import source_engine
from .datalake import merge_parquet_to_l0, write_staging_parquet
from .models import DataSource


def _stream_rows(connection: Connection, table: Table, chunk_size: int) -> Iterable[Mapping[str, Any]]:
    result = connection.execution_options(stream_results=True).execute(select(table))
    while True:
        rows = result.mappings().fetchmany(chunk_size)
        if not rows:
            return
        yield from rows


def run_full_load(
    source: DataSource,
    *,
    schema_name: str,
    table_name: str,
    key_columns: Sequence[str],
    batch_id: str,
    root: Path | None = None,
    chunk_size: int = 5_000,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Extract one source table, write immutable ST Parquet, and merge it into L0."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    count = 0
    metadata = MetaData()
    with source_engine(source) as engine:
        with engine.connect() as connection:
            source_table = Table(table_name, metadata, schema=schema_name, autoload_with=connection)

            def rows() -> Iterable[Mapping[str, Any]]:
                nonlocal count
                for row in _stream_rows(connection, source_table, chunk_size):
                    count += 1
                    yield row

            if progress_callback:
                progress_callback("extract", {"schema": schema_name, "table": table_name})
            staging_path = write_staging_parquet(
                rows(),
                schema_name=schema_name,
                table_name=table_name,
                batch_id=batch_id,
                root=root,
            )

    if count == 0:
        staging_path.unlink(missing_ok=True)
        raise ValueError("source table is empty")
    if progress_callback:
        progress_callback("staging", {"row_count": count, "path": str(staging_path)})
    l0 = merge_parquet_to_l0(
        staging_path,
        schema_name=schema_name,
        table_name=table_name,
        key_columns=key_columns,
        root=root,
    )
    if progress_callback:
        progress_callback("merge", {"row_count": l0["row_count"], "table": l0["table"]})
    return {"source_count": count, "staging_path": str(staging_path), "l0": l0}
