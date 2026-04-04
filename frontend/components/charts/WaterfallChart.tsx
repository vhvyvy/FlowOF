'use client'

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  CartesianGrid,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { WaterfallItem } from '@/types'

interface WaterfallChartProps {
  data: WaterfallItem[]
}

const COLOR_MAP: Record<string, string> = {
  revenue: '#6366f1',
  expense: '#f87171',
  result: '#34d399',
}

export function WaterfallChart({ data }: WaterfallChartProps) {
  return (
    <Card>
      <CardHeader>
        <p className="text-sm font-medium text-slate-400">P&L Waterfall</p>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.5} />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
              labelStyle={{ color: '#94a3b8', fontSize: 12 }}
              itemStyle={{ color: '#e2e8f0', fontSize: 12 }}
              formatter={(v) => [`$${Number(v).toLocaleString()}`, '']}
            />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={COLOR_MAP[entry.type] ?? '#6366f1'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
