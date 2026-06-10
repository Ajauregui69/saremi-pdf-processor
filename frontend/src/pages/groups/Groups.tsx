import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getPersonGroups, getPersonGroup, deletePersonGroup } from '../../api/admin'
import { X, Users, Trash2, ChevronRight, FileText } from 'lucide-react'
import { formatDate, STATUS_COLORS, STATUS_LABELS, DOC_TYPE_LABELS } from '../../lib/utils'
import DocTypeIcon from '../../components/DocTypeIcon'

function ConfidencePill({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 75 ? 'text-emerald-400' : pct >= 45 ? 'text-amber-400' : 'text-red-400'
  return <span className={`font-mono text-xs tabular-nums ${color}`}>{pct}%</span>
}

function GroupPanel({ id, onClose, onDeleted }: { id: string; onClose: () => void; onDeleted: () => void }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['person-group', id],
    queryFn: () => getPersonGroup(id),
  })

  const delMut = useMutation({
    mutationFn: () => deletePersonGroup(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['person-groups'] })
      onDeleted()
      onClose()
    },
  })

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed top-0 right-0 h-full w-full max-w-2xl bg-slate-900 border-l border-slate-800/80 z-50 flex flex-col shadow-2xl">
        {/* header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800/80 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-blue-600/15 flex items-center justify-center">
              <Users className="w-4 h-4 text-blue-400" />
            </div>
            <div>
              <h3 className="text-white font-semibold text-sm leading-tight">
                {isLoading ? '—' : data?.name}
              </h3>
              {data?.institution_name && (
                <p className="text-slate-400 text-xs">{data.institution_name}</p>
              )}
              {data?.notes && (
                <p className="text-slate-500 text-xs mt-0.5 max-w-[320px] truncate">{data.notes}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => {
                if (!confirm(`¿Eliminar el grupo "${data?.name}"? Los documentos no se eliminan.`)) return
                delMut.mutate()
              }}
              disabled={delMut.isPending}
              className="text-slate-500 hover:text-red-400 hover:bg-red-400/10 p-2 rounded-lg transition-colors cursor-pointer"
              title="Eliminar grupo"
            >
              <Trash2 className="w-4 h-4" />
            </button>
            <button onClick={onClose} className="text-slate-400 hover:text-white p-2 rounded-lg transition-colors cursor-pointer">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* content */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="p-5 space-y-3 animate-pulse">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 bg-slate-700 rounded-lg shrink-0" />
                    <div className="flex-1 space-y-2">
                      <div className="h-3.5 w-32 bg-slate-700 rounded" />
                      <div className="h-3 w-48 bg-slate-700 rounded" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : data?.verifications?.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 gap-3 text-center px-6">
              <div className="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center">
                <FileText className="w-5 h-5 text-slate-600" />
              </div>
              <p className="text-slate-500 text-sm">Sin documentos en este grupo</p>
            </div>
          ) : (
            <div className="p-5 space-y-2">
              <p className="text-slate-500 text-xs mb-3">
                {data?.verifications?.length} documento{data?.verifications?.length !== 1 ? 's' : ''}
              </p>
              {data?.verifications?.map((v: any) => (
                <div key={v.id} className="bg-slate-800/50 rounded-xl border border-slate-700/50 px-4 py-3.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="w-9 h-9 rounded-lg bg-slate-700/80 flex items-center justify-center shrink-0 mt-0.5">
                        <DocTypeIcon type={v.document_type} className="w-4 h-4 text-slate-400" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-white text-sm font-medium leading-tight">
                          {DOC_TYPE_LABELS[v.document_type] || v.document_type}
                        </p>
                        {v.original_filename && (
                          <p className="text-slate-400 text-xs truncate max-w-[280px] mt-0.5" title={v.original_filename}>
                            {v.original_filename}
                          </p>
                        )}
                        <p className="text-slate-600 text-xs mt-1">{formatDate(v.created_at)}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <ConfidencePill value={v.confidence_score || 0} />
                      <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${STATUS_COLORS[v.status]}`}>
                        {STATUS_LABELS[v.status] || v.status}
                      </span>
                    </div>
                  </div>
                  {v.conclusion && (
                    <p className="text-slate-400 text-xs mt-2.5 leading-relaxed border-t border-slate-700/50 pt-2.5">
                      {v.conclusion}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

export default function Groups() {
  const [selected, setSelected] = useState<string | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: ['person-groups'],
    queryFn: () => getPersonGroups(),
    staleTime: 0,
    refetchOnWindowFocus: true,
  })

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-white text-xl font-semibold">Personas / Grupos</h2>
        <p className="text-slate-400 text-sm mt-1">
          {data ? `${data.total} grupo${data.total !== 1 ? 's' : ''} de persona` : 'Documentos agrupados por persona'}
        </p>
      </div>

      {isLoading ? (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700/60 overflow-hidden animate-pulse">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-3.5 border-b border-slate-700/40 last:border-0">
              <div className="w-8 h-8 bg-slate-700 rounded-lg" />
              <div className="h-3 w-32 bg-slate-700 rounded" />
              <div className="h-3 w-24 bg-slate-700 rounded" />
              <div className="h-5 w-16 bg-slate-700 rounded-full ml-auto" />
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700/60 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/60 bg-slate-900/30">
                {['Persona', 'Institución', 'Documentos', 'Notas', 'Creado', ''].map((h) => (
                  <th key={h} className="text-left text-slate-500 font-medium text-xs uppercase tracking-wider px-4 py-3 whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/40">
              {data?.data?.map((g: any) => (
                <tr
                  key={g.id}
                  onClick={() => setSelected(g.id === selected ? null : g.id)}
                  className={`cursor-pointer transition-colors group ${
                    selected === g.id ? 'bg-blue-500/8' : 'hover:bg-slate-700/30'
                  }`}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-7 h-7 rounded-lg bg-blue-600/15 flex items-center justify-center shrink-0">
                        <Users className="w-3.5 h-3.5 text-blue-400" />
                      </div>
                      <span className="text-white font-medium">{g.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-xs">
                    {g.institution_name || <span className="text-slate-600 italic">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs bg-slate-700/60 text-slate-300 px-2.5 py-0.5 rounded-full">
                      {g.doc_count ?? 0} doc{g.doc_count !== 1 ? 's' : ''}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-xs max-w-[180px] truncate">
                    {g.notes || <span className="text-slate-700 italic">—</span>}
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">{formatDate(g.created_at)}</td>
                  <td className="px-4 py-3">
                    <ChevronRight className={`w-4 h-4 transition-transform opacity-0 group-hover:opacity-100 ${
                      selected === g.id ? 'rotate-90 text-blue-400 opacity-100' : 'text-slate-500'
                    }`} />
                  </td>
                </tr>
              ))}
              {data?.data?.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center">
                    <div className="flex flex-col items-center gap-2.5">
                      <div className="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center">
                        <Users className="w-5 h-5 text-slate-600" />
                      </div>
                      <p className="text-slate-500 text-sm">Sin grupos creados</p>
                      <p className="text-slate-600 text-xs">Selecciona documentos en Verificaciones y pulsa "Agrupar"</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <GroupPanel
          id={selected}
          onClose={() => setSelected(null)}
          onDeleted={() => setSelected(null)}
        />
      )}
    </div>
  )
}
