/** Shared helpers for qualitative case UI (admin + owner). */

export function formatSentForReviewDisplay(iso: string): string {
  const then = new Date(iso)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - then.getTime()) / 86400000)
  if (diffDays < 1) return 'менее суток назад'
  if (diffDays <= 7) return `${diffDays} дней назад`
  return then.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function truncateDiagnosis(text: string, max = 200): string {
  const t = text.trim()
  if (t.length <= max) return t
  return `${t.slice(0, max)}...`
}

export function fmtRuDate(d: string | null | undefined): string {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export const PRIORITY_LABELS: Record<string, string> = {
  high: 'Высокий',
  normal: 'Обычный',
  low: 'Низкий',
}

export const STAGE_LABELS_OWNER: Record<string, string> = {
  detected: 'Обнаружен',
  in_progress: 'В работе',
  hold: 'Холд',
  review_due: 'На проверке',
  awaiting_review: 'Ожидает оценки',
  closed: 'Закрыт',
  cancelled: 'Отменён',
}

export const CHANGED_BY_LABEL: Record<string, string> = {
  admin: 'Администратор',
  system: 'Система',
  owner: 'Овнер',
}
