import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getVerifications, deleteVerification, createPersonGroup, cancelProcessing } from '../../api/admin'
import { ChevronRight, RefreshCw, Trash2, Users, CheckSquare, Square, X } from 'lucide-react'
import { formatDate, STATUS_COLORS, STATUS_LABELS, DOC_TYPE_LABELS } from '../../lib/utils'
import DocTypeIcon from '../../components/DocTypeIcon'
import VerificationPanel from '../../components/VerificationPanel'

function CreateGroupModal({ ids, onClose, onCreated }: { ids: string[]; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [notes, setNotes] = useState('')
  const qc = useQueryClient()
  const mut = useMutation({
    mutationFn: () => createPersonGroup({ name: name.trim(), notes: notes.trim() || undefined, verification_ids: ids }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['person-groups'] }); onCreated(); onClose() },
  })
  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-50" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-sm bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl p-6">
        <h3 className="text-white font-semibold text-base mb-1">Crear grupo de persona</h3>
        <p className="text-slate-500 text-xs mb-4">{ids.length} documento{ids.length !== 1 ? 's' : ''} seleccionado{ids.length !== 1 ? 's' : ''}</p>
        <div className="space-y-3">
          <div>
            <label className="text-slate-400 text-xs font-medium mb-1.5 block">Nombre de la persona *</label>
            <input
              autoFocus
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Ej: Juan Pérez García"
              className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2.5 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-all"
            />
          </div>
          <div>
            <label className="text-slate-400 text-xs font-medium mb-1.5 block">Notas (opcional)</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              className="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2.5 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-all resize-none"
            />
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 px-4 py-2 text-sm bg-slate-800 text-slate-300 rounded-xl hover:bg-slate-700 transition-colors cursor-pointer">Cancelar</button>
          <button
            disabled={!name.trim() || mut.isPending}
            onClick={() => mut.mutate()}
            className="flex-1 px-4 py-2 text-sm bg-blue-600 text-white rounded-xl hover:bg-blue-500 transition-colors disabled:opacity-50 cursor-pointer"
          >
            {mut.isPending ? 'Creando...' : 'Crear grupo'}
          </button>
        </div>
      </div>
    </>
  )
}

export default function Verifications() {
  const [selected, setSelected] = useState<string | null>(null)
  const [filters, setFilters] = useState({ document_type: '', status: '' })
  const [page, setPage] = useState(1)
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())
  const [showGroupModal, setShowGroupModal] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const qc = useQueryClient()
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['verifications', filters, page],
    queryFn: () => getVerifications({ page, limit: 20, ...filters }),
    staleTime: 0,
    refetchOnWindowFocus: true,
    refetchInterval: 8000,
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteVerification(id),
    onSuccess: (_, id) => {
      if (selected === id) setSelected(null)
      setCheckedIds(prev => { const s = new Set(prev); s.delete(id); return s })
      qc.invalidateQueries({ queryKey: ['verifications'] })
    },
  })

  const cancelMut = useMutation({
    mutationFn: (id: string) => cancelProcessing(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['verifications'] }),
  })

  const allIds: string[] = data?.data?.map((v: any) => v.id) ?? []
  const allChecked = allIds.length > 0 && allIds.every(id => checkedIds.has(id))
  const toggleAll = () => {
    if (allChecked) setCheckedIds(new Set())
    else setCheckedIds(new Set(allIds))
  }
  const toggleOne = (id: string) => {
    setCheckedIds(prev => {
      const s = new Set(prev)
      s.has(id) ? s.delete(id) : s.add(id)
      return s
    })
  }

  const handleDelete = (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    if (!confirm('¿Eliminar esta verificación y su archivo? Esta acción no se puede deshacer.')) return
    setDeletingId(id)
    deleteMut.mutate(id, { onSettled: () => setDeletingId(null) })
  }

  const selectStyles = "bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-slate-300 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-all cursor-pointer"

  return (
    <div className="flex h-full gap-0">
      <div className="flex-1 min-w-0 space-y-4 transition-all duration-300">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-white text-xl font-semibold">Verificaciones</h2>
            <p className="text-slate-400 text-sm mt-0.5">
              {data ? `${data.total} en total` : 'Historial de verificaciones'}
              {checkedIds.size > 0 && <span className="ml-2 text-blue-400 font-medium">· {checkedIds.size} seleccionados</span>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {checkedIds.size > 0 && (
              <button
                onClick={() => setShowGroupModal(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-500 transition-colors cursor-pointer"
              >
                <Users className="w-3.5 h-3.5" />
                Agrupar ({checkedIds.size})
              </button>
            )}
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-slate-800 border border-slate-700 text-slate-300 rounded-lg hover:bg-slate-700 transition-colors disabled:opacity-50 cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
              Actualizar
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-3 flex-wrap">
          <select
            value={filters.document_type}
            onChange={(e) => { setFilters({ ...filters, document_type: e.target.value }); setPage(1) }}
            className={selectStyles}
          >
            <option value="">Todos los tipos</option>
            {Object.entries(DOC_TYPE_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
          <select
            value={filters.status}
            onChange={(e) => { setFilters({ ...filters, status: e.target.value }); setPage(1) }}
            className={selectStyles}
          >
            <option value="">Todos los estados</option>
            {Object.entries(STATUS_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </div>

        {isLoading ? (
          <div className="bg-slate-800/50 rounded-xl border border-slate-700/60 overflow-hidden animate-pulse">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-3.5 border-b border-slate-700/40 last:border-0">
                <div className="w-4 h-4 bg-slate-700 rounded" />
                <div className="h-3 w-24 bg-slate-700 rounded" />
                <div className="h-3 w-32 bg-slate-700 rounded" />
                <div className="h-5 w-20 bg-slate-700 rounded-full" />
                <div className="h-3 w-10 bg-slate-700 rounded" />
                <div className="h-3 w-28 bg-slate-700 rounded ml-auto" />
              </div>
            ))}
          </div>
        ) : (
          <>
            <div className="bg-slate-800/50 rounded-xl border border-slate-700/60 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700/60 bg-slate-900/30">
                    <th className="px-3 py-3 w-8">
                      <button onClick={toggleAll} className="text-slate-500 hover:text-slate-200 transition-colors cursor-pointer">
                        {allChecked ? <CheckSquare className="w-4 h-4 text-blue-400" /> : <Square className="w-4 h-4" />}
                      </button>
                    </th>
                    {['Tipo', 'Archivo', 'Estado', 'Confianza', 'Fecha', ''].map((h) => (
                      <th key={h} className="text-left text-slate-500 font-medium text-xs uppercase tracking-wider px-3 py-3 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/40">
                  {data?.data?.map((v: any) => v.status === 'processing' ? (
                    <tr key={v.id} className="bg-slate-800/20">
                      <td className="px-3 py-3">
                        <Square className="w-4 h-4 text-slate-700" />
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-2">
                          <div className="w-4 h-4 rounded bg-slate-700 animate-pulse" />
                          <div className="h-3 w-28 rounded bg-slate-700 animate-pulse" />
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        {v.original_filename
                          ? <span className="text-slate-500 text-xs truncate max-w-[160px] block">{v.original_filename}</span>
                          : <div className="h-3 w-32 rounded bg-slate-700 animate-pulse" />}
                      </td>
                      <td className="px-3 py-3">
                        <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-slate-700/50 text-slate-400">
                          <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse" />
                          Analizando...
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <div className="h-3 w-8 rounded bg-slate-700 animate-pulse" />
                      </td>
                      <td className="px-3 py-3 text-slate-500 text-xs whitespace-nowrap">{formatDate(v.created_at)}</td>
                      <td className="px-3 py-3">
                        <button
                          onClick={() => cancelMut.mutate(v.id)}
                          disabled={cancelMut.isPending}
                          title="Cancelar análisis"
                          className="p-1.5 rounded-lg text-slate-600 hover:text-orange-400 hover:bg-orange-400/10 transition-colors disabled:opacity-40 cursor-pointer"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ) : (
                    <tr
                      key={v.id}
                      onClick={() => setSelected(v.id === selected ? null : v.id)}
                      className={`cursor-pointer transition-colors group ${
                        selected === v.id
                          ? 'bg-blue-500/8'
                          : checkedIds.has(v.id)
                          ? 'bg-blue-500/5'
                          : 'hover:bg-slate-700/30'
                      }`}
                    >
                      <td className="px-3 py-3" onClick={e => { e.stopPropagation(); toggleOne(v.id) }}>
                        {checkedIds.has(v.id)
                          ? <CheckSquare className="w-4 h-4 text-blue-400" />
                          : <Square className="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition-colors" />}
                      </td>
                      <td className="px-3 py-3 text-slate-200 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-500">
                            <DocTypeIcon type={v.document_type} className="w-3.5 h-3.5" />
                          </span>
                          {DOC_TYPE_LABELS[v.document_type] || v.document_type}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-slate-400 max-w-[160px] truncate text-xs" title={v.original_filename || ''}>
                        {v.original_filename || <span className="text-slate-600 italic">sin nombre</span>}
                      </td>
                      <td className="px-3 py-3">
                        <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${STATUS_COLORS[v.status]}`}>
                          {STATUS_LABELS[v.status] || v.status}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-slate-300 font-mono text-xs tabular-nums">
                        {((v.confidence_score || 0) * 100).toFixed(0)}%
                      </td>
                      <td className="px-3 py-3 text-slate-500 whitespace-nowrap text-xs">{formatDate(v.created_at)}</td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={(e) => handleDelete(e, v.id)}
                            disabled={deletingId === v.id}
                            className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-400/10 transition-colors cursor-pointer"
                            title="Eliminar"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                          <ChevronRight className={`w-4 h-4 transition-transform ${selected === v.id ? 'rotate-90 text-blue-400' : 'text-slate-500'}`} />
                        </div>
                      </td>
                    </tr>
                  ))}
                  {data?.data?.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-12 text-center">
                        <div className="flex flex-col items-center gap-2">
                          <div className="w-10 h-10 rounded-full bg-slate-800 flex items-center justify-center">
                            <DocTypeIcon type="unknown" className="w-5 h-5 text-slate-600" />
                          </div>
                          <p className="text-slate-500 text-sm">Sin verificaciones registradas</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {data?.total > 20 && (
              <div className="flex items-center justify-between text-sm text-slate-400">
                <p>{data.total} resultados</p>
                <div className="flex gap-2">
                  <button disabled={page === 1} onClick={() => setPage(page - 1)}
                    className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg disabled:opacity-40 hover:bg-slate-700 transition-colors cursor-pointer">
                    Anterior
                  </button>
                  <button disabled={page * 20 >= data.total} onClick={() => setPage(page + 1)}
                    className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg disabled:opacity-40 hover:bg-slate-700 transition-colors cursor-pointer">
                    Siguiente
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {selected && (
        <VerificationPanel
          id={selected}
          onClose={() => setSelected(null)}
          onDelete={(id) => {
            if (!confirm('¿Eliminar esta verificación y su archivo?')) return
            setDeletingId(id)
            deleteMut.mutate(id, { onSettled: () => setDeletingId(null) })
          }}
        />
      )}

      {showGroupModal && (
        <CreateGroupModal
          ids={Array.from(checkedIds)}
          onClose={() => setShowGroupModal(false)}
          onCreated={() => setCheckedIds(new Set())}
        />
      )}
    </div>
  )
}
