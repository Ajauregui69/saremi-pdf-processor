import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getManualReviews, deleteVerification } from '../../api/admin'
import { ChevronRight, CheckCircle2 } from 'lucide-react'
import { formatDate, DOC_TYPE_LABELS, STATUS_LABELS, STATUS_COLORS } from '../../lib/utils'
import DocTypeIcon from '../../components/DocTypeIcon'
import VerificationPanel from '../../components/VerificationPanel'

export default function ManualReview() {
  const qc = useQueryClient()
  const [showResolved, setShowResolved] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['manual-reviews', showResolved],
    queryFn: () => getManualReviews({ resolved: showResolved }),
    refetchInterval: showResolved ? undefined : 10000,
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteVerification(id),
    onSuccess: (_, id) => {
      if (selectedId === id) setSelectedId(null)
      qc.invalidateQueries({ queryKey: ['manual-reviews'] })
      qc.invalidateQueries({ queryKey: ['verifications'] })
    },
  })

  const openPanel = (review: any) => {
    setSelectedId(review.verification_id)
    setSelectedReviewId(review.id)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white text-xl font-semibold">Revisión Manual</h2>
          <p className="text-slate-400 text-sm mt-1">
            {data ? `${data.total} documento${data.total !== 1 ? 's' : ''} ` : ''}
            {showResolved ? 'resueltos' : 'pendientes de revisión'}
          </p>
        </div>
        <button
          onClick={() => setShowResolved(!showResolved)}
          className="text-sm text-slate-400 hover:text-white border border-slate-700 hover:border-slate-600 px-3 py-2 rounded-xl transition-all cursor-pointer"
        >
          {showResolved ? 'Ver pendientes' : 'Ver resueltos'}
        </button>
      </div>

      {isLoading ? (
        <div className="space-y-2 animate-pulse">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-slate-800/50 rounded-xl border border-slate-700/60 p-4">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 bg-slate-700 rounded-xl shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="flex gap-2">
                    <div className="h-4 w-32 bg-slate-700 rounded" />
                    <div className="h-4 w-20 bg-slate-700 rounded-full" />
                  </div>
                  <div className="h-3 w-64 bg-slate-700 rounded" />
                  <div className="h-3 w-40 bg-slate-700 rounded" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {data?.data?.map((review: any) => (
            <div
              key={review.id}
              onClick={() => openPanel(review)}
              className={`bg-slate-800/50 rounded-xl border transition-all cursor-pointer group ${
                selectedId === review.verification_id
                  ? 'border-blue-500/40 bg-blue-500/5'
                  : 'border-slate-700/60 hover:border-slate-600/80 hover:bg-slate-800/70'
              }`}
            >
              <div className="flex items-center gap-4 p-4">
                <div className="w-10 h-10 rounded-xl bg-slate-700/60 flex items-center justify-center shrink-0">
                  <DocTypeIcon type={review.document_type} className="w-5 h-5 text-slate-400" />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="text-white font-medium text-sm">
                      {DOC_TYPE_LABELS[review.document_type] || review.document_type}
                    </span>
                    <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${STATUS_COLORS[review.status] || 'bg-slate-700 text-slate-300'}`}>
                      {STATUS_LABELS[review.status] || review.status}
                    </span>
                    <span className="text-slate-500 text-xs tabular-nums">
                      {((review.confidence_score || 0) * 100).toFixed(0)}% confianza
                    </span>
                    {showResolved && review.decision && (
                      <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${
                        review.decision === 'approved'
                          ? 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/25'
                          : 'bg-red-500/15 text-red-400 ring-1 ring-red-500/25'
                      }`}>
                        {review.decision === 'approved' ? 'Aprobado' : 'Rechazado'}
                      </span>
                    )}
                  </div>

                  {review.conclusion && (
                    <p className="text-slate-400 text-xs line-clamp-2 mb-1 leading-relaxed">{review.conclusion}</p>
                  )}

                  {showResolved && review.notes && (
                    <p className="text-slate-500 text-xs italic">"{review.notes}"</p>
                  )}

                  <div className="flex items-center gap-3 text-xs text-slate-500 mt-1.5">
                    <span>{review.institution_name || 'Sin institución'}</span>
                    <span>·</span>
                    <span>{formatDate(review.created_at)}</span>
                    {review.assigned_to && (
                      <>
                        <span>·</span>
                        <span>Resuelto por {review.assigned_to}</span>
                      </>
                    )}
                  </div>
                </div>

                <ChevronRight className={`w-4 h-4 shrink-0 transition-transform ${
                  selectedId === review.verification_id ? 'rotate-90 text-blue-400' : 'text-slate-600 group-hover:text-slate-400'
                }`} />
              </div>
            </div>
          ))}

          {data?.data?.length === 0 && (
            <div className="text-center py-16 text-slate-500">
              <div className="w-16 h-16 rounded-full bg-slate-800 flex items-center justify-center mx-auto mb-4">
                <CheckCircle2 className="w-8 h-8 text-emerald-500/60" />
              </div>
              <p className="text-base font-medium text-slate-400">
                {showResolved ? 'Sin revisiones resueltas' : 'Sin pendientes de revisión'}
              </p>
              {!showResolved && (
                <p className="text-sm mt-1 text-slate-500">Todos los documentos fueron procesados automáticamente</p>
              )}
            </div>
          )}
        </div>
      )}

      {selectedId && (
        <VerificationPanel
          id={selectedId}
          reviewId={selectedReviewId || undefined}
          onClose={() => { setSelectedId(null); setSelectedReviewId(null) }}
          onDelete={(id) => {
            if (!confirm('¿Eliminar esta verificación y su archivo?')) return
            deleteMut.mutate(id)
          }}
        />
      )}
    </div>
  )
}
