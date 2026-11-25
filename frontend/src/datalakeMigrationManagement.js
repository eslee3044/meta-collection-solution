const identityValues = table => [
  table?.system_cd ?? '',
  table?.instance_name ?? '',
  table?.postfix ?? '',
  table?.owner ?? '',
  table?.table_name ?? '',
]

export const migrationIdentityKey = table => JSON.stringify(identityValues(table))

export const getMigrationStatusTargets = (tables, physicalStatuses) => tables.filter(table => {
  const status = physicalStatuses[migrationIdentityKey(table)]
  return status?.st_table_exists === true && status?.table_exists === true
})

export const buildMigrationManagementRows = (tables, physicalStatuses, migrationStatuses) => tables.map(table => {
  const key = migrationIdentityKey(table)
  const physical = physicalStatuses[key] ?? null
  const migration = migrationStatuses[key] ?? null
  const state = migration?.needs_migration === true
    ? 'NEEDS_MIGRATION'
    : physical?.status === 'UNKNOWN' || physical?.status === 'BLOCKED'
      ? 'CHECK_FAILED'
      : migration?.status === 'UNKNOWN'
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
