const identityValues = table => [
  table?.system_cd ?? '',
  table?.instance_name ?? '',
  table?.postfix ?? '',
  table?.owner ?? '',
  table?.table_name ?? '',
]

export const migrationIdentityKey = table => JSON.stringify(identityValues(table))

export const getMigrationStatusTargets = (tables, _physicalStatuses) => tables

export const buildMigrationManagementRows = (tables, physicalStatuses, migrationStatuses) => tables.map(table => {
  const key = migrationIdentityKey(table)
  const physical = physicalStatuses[key] ?? null
  const migration = migrationStatuses[key] ?? null
  const state = migration?.needs_migration === true
    ? 'NEEDS_MIGRATION'
    : physical?.status === 'UNKNOWN' || physical?.status === 'BLOCKED'
      ? 'CHECK_FAILED'
      : migration?.status === 'UNKNOWN' || migration?.status === 'BLOCKED'
        ? 'CHECK_FAILED'
        : migration?.status === 'UNAVAILABLE'
          ? 'UNAVAILABLE'
          : physical?.st_table_exists !== true || physical?.table_exists !== true
            ? 'CREATE_REQUIRED'
            : migration
              ? 'CURRENT'
              : 'CHECK_PENDING'
  return { table, key, physical, migration, state }
})

export const canCloseMigrationModalOnEscape = ({ busy, confirming }) => !busy && !confirming

export const getMigrationNeededRows = (rows, query = '') => {
  const normalizedQuery = query.trim().toLowerCase()
  const actionableStates = new Set(['NEEDS_MIGRATION', 'CREATE_REQUIRED', 'CHECK_FAILED', 'UNAVAILABLE'])
  return rows.filter(row => {
    if (!actionableStates.has(row.state)) return false
    if (!normalizedQuery) return true
    const haystack = `${row.table.system_cd ?? ''} ${row.table.instance_name ?? ''} ${row.table.postfix ?? ''} ${row.table.owner ?? ''} ${row.table.table_name ?? ''}`.toLowerCase()
    return haystack.includes(normalizedQuery)
  })
}
