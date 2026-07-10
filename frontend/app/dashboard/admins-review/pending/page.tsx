'use client'

import { useRouter } from 'next/navigation'
import { ClipboardList, Loader2, MessageSquare } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { usePendingQualitativeList } from '@/lib/hooks/usePendingQualitative'
import {
  formatSentForReviewDisplay,
  truncateDiagnosis,
} from '@/lib/qualitativeCase'
import { cn } from '@/lib/utils'

export default function PendingQualitativePage() {
  const router = useRouter()
  const { data, isLoading } = usePendingQualitativeList()

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-100">
          Качественные кейсы на оценке
        </h1>
        <p className="text-sm text-slate-400 mt-0.5">
          Кейсы, отправленные администраторами на вашу оценку
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-36 w-full rounded-xl" />
          ))}
        </div>
      ) : !data?.items.length ? (
        <div className="flex flex-col items-center justify-center py-16 px-6 rounded-xl border border-slate-700/50 bg-slate-800/30">
          <ClipboardList className="h-10 w-10 text-slate-600 mb-3" />
          <p className="text-sm text-slate-400">Нет качественных кейсов на оценке</p>
        </div>
      ) : (
        <div className="space-y-3">
          {data.items.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => router.push(`/dashboard/admins-review/cases/${item.id}`)}
              className={cn(
                'w-full text-left rounded-xl border border-slate-700/50 bg-slate-800/40',
                'p-4 hover:border-amber-500/30 hover:bg-slate-800/60 transition-colors',
              )}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-100 truncate">
                    {item.chatter_display_name || item.om_user_id}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">{item.om_user_id}</p>
                </div>
                <span className="shrink-0 text-xs font-medium px-2.5 py-1 rounded-full bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/30">
                  {item.category}
                </span>
              </div>

              <p className="text-sm text-slate-300 leading-relaxed mb-3">
                {truncateDiagnosis(item.diagnosis_text)}
              </p>

              <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                <span>
                  {item.admin.name || 'Админ'} · отправлено{' '}
                  {formatSentForReviewDisplay(item.sent_for_review_at)}
                </span>
                <span className="flex items-center gap-1 shrink-0 text-slate-400">
                  <MessageSquare className="h-3.5 w-3.5" />
                  {item.activities_count} активностей
                </span>
              </div>
            </button>
          ))}
        </div>
      )}

      {!isLoading && (data?.total ?? 0) > (data?.items.length ?? 0) && (
        <p className="text-xs text-slate-500 text-center mt-4">
          Показано {data?.items.length} из {data?.total}
        </p>
      )}
    </div>
  )
}
