import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getVerification, reverifyVerification, resolveReview } from '../api/admin'
import { X, FileText, Download, Eye, RefreshCw, Trash2, MessageSquare, CheckCircle, XCircle, CheckCircle2, AlertTriangle, MinusCircle, SkipForward, ChevronDown, ChevronUp } from 'lucide-react'
import { formatDate, STATUS_COLORS, STATUS_LABELS, DOC_TYPE_LABELS } from '../lib/utils'
import DocTypeIcon from './DocTypeIcon'

function CheckBadge({ status }: { status: string }) {
  const styles: Record<string, { className: string; icon: React.ReactNode }> = {
    passed:  { className: 'text-emerald-400 bg-emerald-500/15 ring-1 ring-emerald-500/20', icon: <CheckCircle2 className="w-3 h-3" /> },
    failed:  { className: 'text-red-400 bg-red-500/15 ring-1 ring-red-500/20',             icon: <XCircle className="w-3 h-3" /> },
    warning: { className: 'text-amber-400 bg-amber-500/15 ring-1 ring-amber-500/20',       icon: <AlertTriangle className="w-3 h-3" /> },
    skipped: { className: 'text-slate-400 bg-slate-700/50 ring-1 ring-slate-600/30',       icon: <MinusCircle className="w-3 h-3" /> },
  }
  const s = styles[status] || styles.skipped
  return (
    <span className={`inline-flex items-center justify-center w-5 h-5 rounded-md shrink-0 ${s.className}`}>
      {s.icon}
    </span>
  )
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 75 ? 'bg-emerald-500' : pct >= 45 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 h-1.5 bg-slate-700/80 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-300 w-8 text-right tabular-nums font-medium">{pct}%</span>
    </div>
  )
}

function ExtractedDataTable({ data }: { data: Record<string, any> }) {
  const SKIP = ['_raw_text']
  const entries = Object.entries(data).filter(([k]) => !SKIP.includes(k))
  if (!entries.length) return <p className="text-slate-500 text-xs">Sin datos extraídos</p>

  const LABELS: Record<string, string> = {
    full_name: 'Nombre completo', employee_name: 'Nombre del empleado',
    employer_name: 'Empresa', employee_rfc: 'RFC empleado', rfc: 'RFC',
    gross_salary: 'Salario bruto', net_salary: 'Salario neto',
    payment_period: 'Período de pago', position: 'Cargo/Puesto',
    start_date: 'Fecha de ingreso', annual_income: 'Ingreso anual',
    fiscal_year: 'Año fiscal', curp: 'CURP', voter_id: 'Clave de elector',
    expiry_date: 'Vencimiento', birth_date: 'Fecha de nacimiento',
    state: 'Estado', municipality: 'Municipio', section: 'Sección',
    account_holder: 'Titular', bank_name: 'Banco', account_number: 'No. cuenta',
    period_start: 'Período inicio', period_end: 'Período fin',
    opening_balance: 'Saldo inicial', closing_balance: 'Saldo final',
    address: 'Dirección', service_provider: 'Proveedor', issue_date: 'Fecha emisión',
  }

  return (
    <div className="divide-y divide-slate-700/50">
      {entries.map(([key, val]) => (
        <div key={key} className="grid grid-cols-5 gap-2 py-2.5 text-xs">
          <span className="col-span-2 text-slate-500 truncate">{LABELS[key] || key}</span>
          <span className="col-span-3 text-slate-200 break-words">
            {typeof val === 'object' ? JSON.stringify(val) : String(val ?? '—')}
          </span>
        </div>
      ))}
    </div>
  )
}

function DocViewer({ verificationId, hasFile }: { verificationId: string; hasFile: boolean }) {
  const token = localStorage.getItem('saremi_token') || 'dev-token'
  const fileUrl = `/admin/verifications/${verificationId}/file?token=${encodeURIComponent(token)}`

  if (!hasFile) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-10 gap-3">
        <div className="w-16 h-16 rounded-full bg-slate-800 flex items-center justify-center">
          <FileText className="w-7 h-7 text-slate-600" />
        </div>
        <p className="text-slate-400 text-sm font-medium">Documento no disponible</p>
        <p className="text-slate-600 text-xs max-w-xs leading-relaxed">
          Los documentos subidos antes de esta actualización no se almacenaron.
        </p>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800/80 shrink-0 bg-slate-900/30">
        <p className="text-slate-500 text-xs">Vista del documento</p>
        <div className="flex items-center gap-3">
          <button
            onClick={() => window.open(fileUrl, '_blank')}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors cursor-pointer"
          >
            <Eye className="w-3.5 h-3.5" />
            Abrir en pestaña
          </button>
          <a
            href={fileUrl}
            download
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            Descargar
          </a>
        </div>
      </div>
      <div className="flex-1 min-h-0 bg-slate-950">
        <iframe key={verificationId} src={fileUrl} className="w-full h-full border-0" title="documento" />
      </div>
    </div>
  )
}

function ManualResolutionSection({ verificationId, reviewId }: { verificationId: string; reviewId?: string }) {
  const [conclusion, setConclusion] = useState('')
  const qc = useQueryClient()

  const resolveMut = useMutation({
    mutationFn: ({ decision }: { decision: 'approved' | 'rejected' }) => {
      const id = reviewId || verificationId
      return resolveReview(id, decision, conclusion.trim() || undefined)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['verification', verificationId] })
      qc.invalidateQueries({ queryKey: ['manual-reviews'] })
      qc.invalidateQueries({ queryKey: ['verifications'] })
    },
  })

  return (
    <div className="border-t border-orange-500/20 bg-orange-500/5 px-5 py-4 shrink-0">
      <div className="flex items-center gap-2 mb-3">
        <MessageSquare className="w-4 h-4 text-orange-400" />
        <p className="text-orange-300 text-sm font-medium">Resolución manual requerida</p>
      </div>
      <div className="mb-3">
        <label className="text-slate-400 text-xs font-medium mb-1.5 block">Conclusión manual</label>
        <textarea
          value={conclusion}
          onChange={e => setConclusion(e.target.value)}
          rows={3}
          placeholder="Escribe aquí tu análisis y conclusión sobre el documento..."
          className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3.5 py-2.5 text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-orange-500/40 focus:border-orange-500/40 transition-all resize-none"
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => resolveMut.mutate({ decision: 'approved' })}
          disabled={resolveMut.isPending}
          className="flex-1 flex items-center justify-center gap-1.5 bg-emerald-600/80 hover:bg-emerald-600 disabled:opacity-50 text-white px-3 py-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer"
        >
          <CheckCircle className="w-4 h-4" />
          Aprobar
        </button>
        <button
          onClick={() => resolveMut.mutate({ decision: 'rejected' })}
          disabled={resolveMut.isPending}
          className="flex-1 flex items-center justify-center gap-1.5 bg-red-600/80 hover:bg-red-600 disabled:opacity-50 text-white px-3 py-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer"
        >
          <XCircle className="w-4 h-4" />
          Rechazar
        </button>
      </div>
      {resolveMut.isSuccess && (
        <p className="text-emerald-400 text-xs mt-2 text-center font-medium">Resolución guardada correctamente</p>
      )}
    </div>
  )
}

function ConclusionBlock({ conclusion, warnings }: { conclusion: string; warnings?: string[] }) {
  const [expanded, setExpanded] = useState(false)
  const LINES_THRESHOLD = 3
  const lines = conclusion.split('\n').filter(Boolean)
  const isLong = conclusion.length > 220 || lines.length > LINES_THRESHOLD

  return (
    <div className="px-5 py-4 border-b border-slate-800/80">
      <p className="text-slate-500 text-xs font-semibold mb-2 uppercase tracking-wider">Conclusión automática</p>

      <div className={`relative ${!expanded && isLong ? 'max-h-[4.5rem] overflow-hidden' : ''}`}>
        <p className="text-slate-200 text-sm leading-relaxed">{conclusion}</p>
        {!expanded && isLong && (
          <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-slate-900 to-transparent pointer-events-none" />
        )}
      </div>

      {isLong && (
        <button
          onClick={() => setExpanded(v => !v)}
          className="mt-2 flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors cursor-pointer"
        >
          {expanded ? <><ChevronUp className="w-3.5 h-3.5" /> Ver menos</> : <><ChevronDown className="w-3.5 h-3.5" /> Ver más</>}
        </button>
      )}

      {warnings && warnings.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {warnings.map((w: string, i: number) => (
            <p key={i} className="text-amber-400 text-xs flex items-start gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {w}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

interface VerificationPanelProps {
  id: string
  onClose: () => void
  onDelete: (id: string) => void
  reviewId?: string
}

export default function VerificationPanel({ id, onClose, onDelete, reviewId }: VerificationPanelProps) {
  const [tab, setTab] = useState<'doc' | 'data' | 'notes'>('doc')
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['verification', id],
    queryFn: () => getVerification(id),
  })

  const reverifyMut = useMutation({
    mutationFn: () => reverifyVerification(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['verification', id] })
      qc.invalidateQueries({ queryKey: ['verifications'] })
      qc.invalidateQueries({ queryKey: ['manual-reviews'] })
    },
  })

  const isManualReview = data?.status === 'manual_review'

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />

      <div className="fixed top-0 right-0 h-full w-full max-w-2xl bg-slate-900 border-l border-slate-800/80 z-50 flex flex-col shadow-2xl">
        {/* header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800/80 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-slate-800 flex items-center justify-center shrink-0">
              <DocTypeIcon type={data?.document_type} className="w-5 h-5 text-slate-400" />
            </div>
            <div>
              <h3 className="text-white font-semibold text-sm leading-tight">
                {DOC_TYPE_LABELS[data?.document_type] || data?.document_type || '…'}
              </h3>
              {data?.original_filename && (
                <p className="text-slate-400 text-xs truncate max-w-[240px] mt-0.5" title={data.original_filename}>
                  {data.original_filename}
                </p>
              )}
              <p className="text-slate-500 text-xs">{data ? formatDate(data.created_at) : '—'}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            {data && (
              <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${STATUS_COLORS[data.status] || ''}`}>
                {STATUS_LABELS[data.status] || data.status}
              </span>
            )}
            <button
              onClick={() => reverifyMut.mutate()}
              disabled={reverifyMut.isPending}
              title="Re-verificar documento"
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-lg transition-colors cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${reverifyMut.isPending ? 'animate-spin' : ''}`} />
              {reverifyMut.isPending ? 'Verificando...' : 'Re-verificar'}
            </button>
            <button
              onClick={() => onDelete(id)}
              className="text-slate-500 hover:text-red-400 hover:bg-red-400/10 p-1.5 rounded-lg transition-colors cursor-pointer"
              title="Eliminar verificación"
            >
              <Trash2 className="w-4 h-4" />
            </button>
            <button onClick={onClose} className="text-slate-400 hover:text-white p-1.5 rounded-lg transition-colors cursor-pointer">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* re-verify feedback */}
        {reverifyMut.isSuccess && (
          <div className="px-5 py-2.5 bg-blue-500/10 border-b border-blue-500/20 shrink-0">
            <p className="text-blue-300 text-xs font-medium">Documento re-verificado exitosamente.</p>
          </div>
        )}
        {reverifyMut.isError && (
          <div className="px-5 py-2.5 bg-red-500/10 border-b border-red-500/20 shrink-0">
            <p className="text-red-300 text-xs">Error al re-verificar. Revisa que el archivo esté disponible.</p>
          </div>
        )}

        {/* Tab bar */}
        <div className="flex border-b border-slate-800/80 px-5 gap-1 shrink-0">
          {([
            { id: 'doc'   as const, label: 'Documento',       icon: Eye },
            { id: 'data'  as const, label: 'Datos extraídos', icon: FileText },
            { id: 'notes' as const, label: 'Verificaciones',  icon: MessageSquare },
          ]).map(({ id: tid, label, icon: Icon }) => (
            <button
              key={tid}
              onClick={() => setTab(tid)}
              className={`flex items-center gap-1.5 py-3 px-1 text-xs font-medium border-b-2 transition-all cursor-pointer ${
                tab === tid
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-slate-500 hover:text-slate-300'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="space-y-3 w-64 animate-pulse">
              <div className="h-4 bg-slate-800 rounded w-3/4 mx-auto" />
              <div className="h-4 bg-slate-800 rounded w-1/2 mx-auto" />
            </div>
          </div>
        ) : data ? (
          <div className="flex-1 flex flex-col min-h-0">
            {tab === 'doc' && (
              <div className="flex-1 flex flex-col min-h-0">
                <DocViewer verificationId={id} hasFile={!!data.file_path} />
              </div>
            )}

            {tab !== 'doc' && (
              <div className="flex-1 overflow-y-auto">
                {/* confidence + meta */}
                <div className="px-5 py-4 border-b border-slate-800/80 space-y-3">
                  <div>
                    <p className="text-slate-500 text-xs font-medium mb-1.5">Confianza</p>
                    <ConfidenceBar value={data.confidence_score || 0} />
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                    <div>
                      <span className="text-slate-500">Institución</span>
                      <p className="text-slate-200 truncate mt-0.5">{data.institution_name || '—'}</p>
                    </div>
                    <div>
                      <span className="text-slate-500">Tiempo de proceso</span>
                      <p className="text-slate-200 mt-0.5 tabular-nums">{data.processing_time_ms}ms</p>
                    </div>
                    {data.document_hash && (
                      <div className="col-span-2">
                        <span className="text-slate-500">Hash documento</span>
                        <p className="text-slate-500 font-mono text-xs break-all mt-0.5">{data.document_hash}</p>
                      </div>
                    )}
                  </div>
                </div>

                {/* conclusion */}
                {data.conclusion && (
                  <ConclusionBlock conclusion={data.conclusion} warnings={data.warnings} />
                )}

                {/* tab content */}
                <div className="px-5 py-4">
                  {tab === 'data' && <ExtractedDataTable data={data.extracted_data || {}} />}

                  {tab === 'notes' && (
                    <div className="space-y-2">
                      {data.checks?.length > 0 ? data.checks.map((c: any, i: number) => (
                        <div key={i} className="flex items-start gap-3 bg-slate-800/50 rounded-xl px-3.5 py-3 border border-slate-700/40">
                          <CheckBadge status={c.status} />
                          <div className="min-w-0">
                            <p className="text-slate-200 text-xs font-mono leading-tight">{c.name}</p>
                            <p className="text-slate-400 text-xs mt-1 leading-relaxed">{c.detail}</p>
                          </div>
                        </div>
                      )) : (
                        <div className="flex flex-col items-center gap-2 py-8">
                          <SkipForward className="w-8 h-8 text-slate-700" />
                          <p className="text-slate-500 text-xs">Sin verificaciones disponibles</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {isManualReview && (
              <ManualResolutionSection verificationId={id} reviewId={reviewId} />
            )}
          </div>
        ) : null}
      </div>
    </>
  )
}
