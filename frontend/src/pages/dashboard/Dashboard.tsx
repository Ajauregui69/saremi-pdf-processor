import { useQuery } from '@tanstack/react-query'
import { getStats } from '../../api/admin'
import { ShieldCheck, Building2, ClipboardList, TrendingUp } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { formatDateShort, DOC_TYPE_LABELS, STATUS_LABELS } from '../../lib/utils'

function StatCard({ label, value, icon: Icon, accent }: {
  label: string
  value: number | string
  icon: React.ElementType
  accent: { icon: string; bg: string; glow: string }
}) {
  return (
    <div className="bg-slate-800/50 rounded-xl p-5 border border-slate-700/60 hover:border-slate-600/80 transition-all duration-200 group">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-slate-400 text-xs font-medium uppercase tracking-wider">{label}</p>
          <p className="text-white text-3xl font-bold mt-2.5 tracking-tight tabular-nums">{value ?? '—'}</p>
        </div>
        <div className={`p-2.5 rounded-xl ${accent.bg} shrink-0`}>
          <Icon className={`w-5 h-5 ${accent.icon}`} />
        </div>
      </div>
    </div>
  )
}

function StatSkeleton() {
  return (
    <div className="bg-slate-800/50 rounded-xl p-5 border border-slate-700/60 animate-pulse">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2.5 flex-1">
          <div className="h-3 w-28 bg-slate-700 rounded" />
          <div className="h-9 w-16 bg-slate-700 rounded mt-3" />
        </div>
        <div className="w-10 h-10 bg-slate-700 rounded-xl shrink-0" />
      </div>
    </div>
  )
}

const STAT_ACCENTS = [
  { icon: 'text-blue-400',    bg: 'bg-blue-500/15',    glow: '' },
  { icon: 'text-emerald-400', bg: 'bg-emerald-500/15', glow: '' },
  { icon: 'text-violet-400',  bg: 'bg-violet-500/15',  glow: '' },
  { icon: 'text-orange-400',  bg: 'bg-orange-500/15',  glow: '' },
]

export default function Dashboard() {
  const { data, isLoading } = useQuery({ queryKey: ['stats'], queryFn: getStats, refetchInterval: 30_000 })

  const s = data?.summary || {}

  const stats = [
    { label: 'Instituciones activas',  value: s.active_institutions ?? 0,     icon: Building2    },
    { label: 'Verificadas (30d)',       value: s.verified_month ?? 0,          icon: TrendingUp   },
    { label: 'Verificaciones hoy',      value: s.verifications_today ?? 0,     icon: ShieldCheck  },
    { label: 'Revisión pendiente',      value: s.pending_manual_reviews ?? 0,  icon: ClipboardList },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-white text-xl font-semibold">Dashboard</h2>
        <p className="text-slate-400 text-sm mt-1">Resumen de actividad del sistema</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => <StatSkeleton key={i} />)
          : stats.map((s, i) => (
              <StatCard key={s.label} {...s} accent={STAT_ACCENTS[i]} />
            ))
        }
      </div>

      {/* Tendencia diaria */}
      {data?.daily_trend?.length > 0 && (
        <div className="bg-slate-800/50 rounded-xl p-5 border border-slate-700/60">
          <div className="mb-5">
            <h3 className="text-white font-semibold text-sm">Verificaciones — últimos 30 días</h3>
            <p className="text-slate-500 text-xs mt-0.5">Documentos verificados vs inválidos por día</p>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={[...data.daily_trend].reverse()} barGap={2}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={(v) => formatDateShort(v)}
                tick={{ fill: '#64748b', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: '#64748b', fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                width={28}
              />
              <Tooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  borderRadius: 10,
                  fontSize: 12,
                }}
                labelStyle={{ color: '#94a3b8', marginBottom: 4 }}
                itemStyle={{ color: '#e2e8f0' }}
                cursor={{ fill: '#1e293b' }}
              />
              <Bar dataKey="verified" name="Verificados" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={24} />
              <Bar dataKey="invalid"  name="Inválidos"   fill="#ef4444" radius={[4, 4, 0, 0]} maxBarSize={24} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Por tipo de documento */}
      {data?.by_document_type?.length > 0 && (
        <div className="bg-slate-800/50 rounded-xl p-5 border border-slate-700/60">
          <div className="mb-4">
            <h3 className="text-white font-semibold text-sm">Por tipo de documento (30d)</h3>
          </div>
          <div className="divide-y divide-slate-700/50">
            {data.by_document_type.map((row: any) => (
              <div key={`${row.document_type}-${row.status}`} className="flex items-center justify-between py-2.5 text-sm">
                <span className="text-slate-300">
                  {DOC_TYPE_LABELS[row.document_type] || row.document_type}
                  <span className="text-slate-500 ml-2">· {STATUS_LABELS[row.status] || row.status}</span>
                </span>
                <span className="text-white font-semibold tabular-nums">{row.total}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
