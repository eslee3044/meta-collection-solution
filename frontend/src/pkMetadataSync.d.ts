export function syncRegisteredPkColumns<T extends { columns?: Array<Record<string, any>> }>(table: T, pkColumns: string[]): T
