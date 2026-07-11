'use client'

import { ArrowDown, ArrowUp, Info, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  fmtDayMonth,
  fmtMetricValue,
  fmtMonthName,
  fmtPrevMonthName,
  pctDelta,
  weekRangeLabel,
  type MetricType,
} from '@/lib/metricFormat'

export interface V2SnapshotValues {
  daily_value?: number | null
  week_avg_value?: number | null
  month_current_value?: number | null
  prev_month_value?: number | null
  snapshot_date?: string | null
  snapshot_as_of?: string | null
}

interface MetricCellProps {
  label: string
  value: number | null | undefined
  sublabel: string
  metric: string
  compareFrom?: number | null
  showDelta?: boolean
}

function MetricCell({ label, value, sublabel, metric, compareFrom, showDelta }: MetricCellProps) {
  const delta = showDelta && compareFrom != null ? pctDelta(compareFrom, value) : null
  return (
    <div className="bg-slate-700/30 rounded-xl p-3 min-w-0">
      <p className="text-xs text-slate-500 mb-1 truncate">{label}</p>
      <p className="text-lg font-bold text-slate-100 truncate">
        {fmtMetricValue(metric, value ?? null)}
      </p>
      <p className="text-xs text-slate-500 mt-1 truncate">{sublabel}</p>
      {delta && (
        <p
          className={cn(
            'text-xs font-medium mt-1 flex items-center gap-0.5',
            delta.improved === true && 'text-green-400',
            delta.improved === false && 'text-red-400',
            delta.improved === null && 'text-slate-500',
          )}
        >
          {delta.improved === true && <ArrowUp className="h-3 w-3" />}
          {delta.improved === false && <ArrowDown className="h-3 w-3" />}
          {delta.improved === null && <Minus className="h-3 w-3" />}
          {delta.pct}
        </p>
      )}
    </div>
  )
}

/** 4 preview cards for create-case modal */
export function BaselinePreviewV2Cards({
  metric,
  preview,
}: {
  metric: MetricType
  preview: {
    daily_value?: number | null
    week_avg_value?: number | null
    month_current_value?: number | null
    prev_month_value?: number | null
    snapshot_date?: string | null
  }
}) {
  const asOf = preview.snapshot_date ?? new Date().toISOString().slice(0, 10)
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2" data-testid="baseline-preview-v2">
      <MetricCell
        label="Вчера"
        value={preview.daily_value}
        sublabel={fmtDayMonth(preview.snapshot_date)}
        metric={metric}
      />
      <MetricCell
        label="Неделя (среднее)"
        value={preview.week_avg_value}
        sublabel={weekRangeLabel(asOf)}
        metric={metric}
      />
      <MetricCell
        label="Месяц"
        value={preview.month_current_value}
        sublabel={fmtMonthName(asOf)}
        metric={metric}
      />
      <MetricCell
        label="Прошлый месяц"
        value={preview.prev_month_value}
        sublabel={fmtPrevMonthName(asOf)}
        metric={metric}
      />
    </div>
  )
}

export function BaselineV2Flags({
  isEarlyMonth,
  isNewChatter,
}: {
  isEarlyMonth?: boolean
  isNewChatter?: boolean
}) {
  return (
    <div className="space-y-1.5 mt-2">
      {isEarlyMonth && (
        <p className="text-xs text-amber-400/90 bg-amber-500/10 rounded-lg px-2.5 py-1.5" data-testid="flag-early-month">
          ⚠ Кейс в начале месяца. Основное сравнение идёт с прошлым месяцем.
        </p>
      )}
      {isNewChatter && (
        <p className="text-xs text-violet-400/90 bg-violet-500/10 rounded-lg px-2.5 py-1.5" data-testid="flag-new-chatter">
          ⚠ Новый чаттер. За прошлый месяц данных нет — кейс будет закрыт вручную владельцем.
        </p>
      )}
    </div>
  )
}

interface MetricV2BlockProps {
  metric: string
  baseline: V2SnapshotValues
  now?: V2SnapshotValues | null
  outcome?: V2SnapshotValues | null
  isClosed: boolean
  isEarlyMonth?: boolean
  isNewChatter?: boolean
}

function MetricRow({
  title,
  frozen,
  values,
  metric,
  compareBaseline,
  showDelta,
  monthLiveSuffix,
}: {
  title: string
  frozen?: boolean
  values: V2SnapshotValues
  metric: string
  compareBaseline?: V2SnapshotValues
  showDelta?: boolean
  monthLiveSuffix?: boolean
}) {
  const asOf = values.snapshot_as_of ?? values.snapshot_date ?? null
  const monthLabel = monthLiveSuffix
    ? `${fmtMonthName(asOf)} текущ.`
    : fmtMonthName(asOf)

  return (
    <div className="space-y-2">
      <p className={cn('text-xs font-medium', frozen ? 'text-amber-400/80' : 'text-sky-400/80')}>
        {title}
        {frozen && <span className="text-slate-600 font-normal ml-1">(заморожено)</span>}
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <MetricCell
          label="Вчера"
          value={values.daily_value}
          sublabel={fmtDayMonth(values.snapshot_date)}
          metric={metric}
          compareFrom={showDelta ? compareBaseline?.daily_value : undefined}
          showDelta={showDelta}
        />
        <MetricCell
          label="Неделя"
          value={values.week_avg_value}
          sublabel={weekRangeLabel(asOf)}
          metric={metric}
          compareFrom={showDelta ? compareBaseline?.week_avg_value : undefined}
          showDelta={showDelta}
        />
        <MetricCell
          label="Месяц"
          value={values.month_current_value}
          sublabel={monthLabel}
          metric={metric}
          compareFrom={showDelta ? compareBaseline?.month_current_value : undefined}
          showDelta={showDelta}
        />
        <MetricCell
          label="Прошлый месяц"
          value={values.prev_month_value}
          sublabel={fmtPrevMonthName(asOf ?? values.snapshot_date)}
          metric={metric}
          compareFrom={showDelta ? compareBaseline?.prev_month_value : undefined}
          showDelta={showDelta}
        />
      </div>
    </div>
  )
}

/** Case detail page: Точка отсчёта / Сейчас / Итог rows */
export function MetricV2Block({
  metric,
  baseline,
  now,
  outcome,
  isClosed,
  isEarlyMonth,
  isNewChatter,
}: MetricV2BlockProps) {
  const showOutcome = isClosed && outcome
  const showNow = !showOutcome && now

  return (
    <div className="space-y-4" data-testid="metric-v2-block">
      <div className="flex items-center gap-2">
        <p className="text-sm font-medium text-slate-300">Точка отсчёта</p>
        {(isEarlyMonth || isNewChatter) && (
          <span
            className="inline-flex text-slate-500 cursor-help"
            title={
              [
                isEarlyMonth && 'Кейс открыт в первые 7 дней месяца',
                isNewChatter && 'Новый чаттер без данных за прошлый месяц',
              ]
                .filter(Boolean)
                .join('. ')
            }
          >
            <Info className="h-3.5 w-3.5" />
          </span>
        )}
      </div>

      <MetricRow
        title="Точка отсчёта"
        frozen
        values={baseline}
        metric={metric}
      />

      {showNow && (
        <MetricRow
          title="Сейчас"
          values={{
            daily_value: now.daily_value,
            week_avg_value: now.week_avg_value,
            month_current_value: now.month_current_value,
            prev_month_value: baseline.prev_month_value,
            snapshot_date: now.snapshot_date,
            snapshot_as_of: now.snapshot_as_of,
          }}
          metric={metric}
          compareBaseline={baseline}
          showDelta
          monthLiveSuffix
        />
      )}

      {showOutcome && (
        <MetricRow
          title="Итог"
          frozen
          values={outcome}
          metric={metric}
          compareBaseline={baseline}
          showDelta
        />
      )}

      <p className="text-xs text-slate-600 leading-relaxed">
        Основной критерий: Месяц (сейчас) vs Прошлый месяц. Остальные — контекст.
      </p>
    </div>
  )
}
