export function migrationIdentityKey(table: any): string
export function canCloseMigrationModalOnEscape(options: { busy: boolean; confirming: boolean }): boolean
export function getMigrationNeededRows(rows: any[], query?: string): any[]
export function getMigrationStatusTargets(tables: any[], physicalStatuses: Record<string, any>): any[]
export function buildMigrationManagementRows(tables: any[], physicalStatuses: Record<string, any>, migrationStatuses: Record<string, any>): any[]
