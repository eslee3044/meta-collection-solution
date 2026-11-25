export function shouldShowMigrationButton(needsMigration, isDirty, isChecking) {
  return needsMigration === true && !isDirty && !isChecking
}

export function isMigrationRequestCurrent(requestId, currentRequestId, requestedSelected, currentSelected, requestedOriginal, currentOriginal) {
  return requestId === currentRequestId
    && requestedSelected === currentSelected
    && requestedOriginal === currentOriginal
}
