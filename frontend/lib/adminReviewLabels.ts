/** Russian labels for admin review ledger event_type values. */

export const LEDGER_EVENT_LABELS: Record<string, string> = {
  case_opened: 'Открыт кейс',
  case_closed_success: 'Закрыт успехом',
  case_closed_failed: 'Закрыт провалом',
  case_cancelled: 'Отменён',
  guardrail_triggered: 'Guardrail сработал',
  qualitative_success: 'Качественный успех',
  qualitative_failed: 'Качественный провал',
  returned_for_revision: 'Возврат на доработку',
}

export function ledgerEventLabel(eventType: string): string {
  return LEDGER_EVENT_LABELS[eventType] ?? eventType
}

export const CASE_TYPE_LABELS: Record<string, string> = {
  quantitative: 'Количественный',
  qualitative: 'Качественный',
}
