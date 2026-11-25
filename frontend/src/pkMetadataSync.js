function normalizeColumnName(value) {
  return String(value ?? '').trim().toLocaleUpperCase()
}

export function syncRegisteredPkColumns(table, pkColumns) {
  if (!table || !Array.isArray(table.columns)) return table

  const primaryKeyColumns = new Set((pkColumns ?? []).map(normalizeColumnName).filter(Boolean))
  return {
    ...table,
    columns: table.columns.map(column => ({
      ...column,
      pk_yn: primaryKeyColumns.has(normalizeColumnName(column.column_name)) ? 'Y' : 'N',
    })),
  }
}
