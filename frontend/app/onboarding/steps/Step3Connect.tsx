'use client'

import { Button } from '@/components/ui/button'

export default function Step3Connect({
  onComplete,
  data,
}: {
  onComplete: (data: Record<string, unknown>) => void
  data: Record<string, unknown>
}) {
  const src = String(data.source_type ?? 'notion')

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">Подключение</h2>
      {src === 'notion' && (
        <>
          <p className="text-slate-400 text-sm mb-4">
            После онбординга откройте <strong className="text-slate-300">Настройки → Интеграции</strong> и вставьте{' '}
            <span className="text-indigo-300">Notion Internal Integration Secret</span>. Затем в Notion: Share →
            Connections на ваших базах.
          </p>
          <p className="text-slate-500 text-xs mb-6">
            Импорт и сопоставление колонок можно настроить в следующих шагах, когда API будет готов к полному сценарию.
          </p>
        </>
      )}
      {src === 'excel' && (
        <p className="text-slate-400 text-sm mb-6">
          Загрузка Excel/CSV будет доступна из раздела импорта. Пока можно завершить онбординг и вернуться к этому позже.
        </p>
      )}
      {(src === 'google_sheets' || src === 'manual') && (
        <p className="text-slate-400 text-sm mb-6">
          Этот сценарий подключается в следующих версиях. Сейчас можно завершить настройку и пользоваться дашбордом.
        </p>
      )}
      <Button className="w-full" onClick={() => onComplete({})}>
        Понятно, далее
      </Button>
    </div>
  )
}
