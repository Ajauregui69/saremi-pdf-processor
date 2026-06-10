import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getInstitutions, createInstitution, getApiKeys, createApiKey, revokeApiKey } from '../../api/admin'
import { Plus, Key, Copy, Check, X, Building2 } from 'lucide-react'
import { formatDate } from '../../lib/utils'

function Badge({ active }: { active: boolean }) {
  return (
    <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${
      active
        ? 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/25'
        : 'bg-slate-700/50 text-slate-400 ring-1 ring-slate-600/30'
    }`}>
      {active ? 'Activa' : 'Inactiva'}
    </span>
  )
}

const inputClass = "w-full bg-slate-800 border border-slate-700 rounded-xl px-3.5 py-2.5 text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-all"

function ApiKeysModal({ institution, onClose }: { institution: any; onClose: () => void }) {
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const { data: keys = [] } = useQuery({
    queryKey: ['api-keys', institution.id],
    queryFn: () => getApiKeys(institution.id),
  })

  const createMut = useMutation({
    mutationFn: () => createApiKey(institution.id, { label }),
    onSuccess: (data) => {
      setNewKey(data.api_key)
      setLabel('')
      qc.invalidateQueries({ queryKey: ['api-keys', institution.id] })
    },
  })

  const revokeMut = useMutation({
    mutationFn: (keyId: string) => revokeApiKey(institution.id, keyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['api-keys', institution.id] }),
  })

  const copyKey = () => {
    if (newKey) {
      navigator.clipboard.writeText(newKey)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 rounded-2xl border border-slate-800 w-full max-w-lg shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-800">
          <div>
            <h3 className="text-white font-semibold">API Keys</h3>
            <p className="text-slate-500 text-xs mt-0.5">{institution.name}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1.5 rounded-lg transition-colors cursor-pointer"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-5 space-y-4">
          {newKey && (
            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4">
              <p className="text-emerald-400 text-xs mb-2 font-medium">API Key generada — guárdala, no se mostrará de nuevo</p>
              <div className="flex items-center gap-2">
                <code className="text-emerald-300 text-xs flex-1 break-all font-mono">{newKey}</code>
                <button onClick={copyKey} className="shrink-0 text-emerald-400 hover:text-emerald-200 transition-colors p-1 cursor-pointer">
                  {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            </div>
          )}

          <div className="flex gap-2">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Etiqueta (ej: Producción)"
              className={`${inputClass} flex-1`}
            />
            <button
              onClick={() => createMut.mutate()}
              disabled={createMut.isPending}
              className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-3.5 py-2.5 rounded-xl text-sm flex items-center gap-1.5 transition-colors cursor-pointer shrink-0"
            >
              <Plus className="w-4 h-4" />
              Generar
            </button>
          </div>

          <div className="space-y-3 max-h-80 overflow-y-auto">
            {keys.map((k: any) => (
              <div key={k.id} className="bg-slate-800/60 rounded-xl px-4 py-3.5 space-y-2.5 border border-slate-700/50">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-white text-sm font-mono">{k.key_prefix}••••••</p>
                    <p className="text-slate-500 text-xs mt-0.5">
                      {k.label || 'Sin etiqueta'} · Creada {formatDate(k.created_at)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge active={k.active} />
                    {k.active && (
                      <button
                        onClick={() => revokeMut.mutate(k.id)}
                        className="text-slate-500 hover:text-red-400 text-xs transition-colors cursor-pointer"
                      >
                        Revocar
                      </button>
                    )}
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-700/50">
                  <div className="text-center">
                    <p className="text-white text-base font-bold tabular-nums">{k.verifications_today ?? 0}</p>
                    <p className="text-slate-500 text-xs">Hoy</p>
                  </div>
                  <div className="text-center">
                    <p className="text-white text-base font-bold tabular-nums">{k.verifications_month ?? 0}</p>
                    <p className="text-slate-500 text-xs">Este mes</p>
                  </div>
                  <div className="text-center">
                    <p className="text-blue-400 text-base font-bold tabular-nums">{k.usage_count ?? 0}</p>
                    <p className="text-slate-500 text-xs">Total</p>
                  </div>
                </div>
                {k.last_used_at && (
                  <p className="text-slate-600 text-xs">Último uso: {formatDate(k.last_used_at)}</p>
                )}
              </div>
            ))}
            {keys.length === 0 && (
              <div className="text-center py-6">
                <Key className="w-8 h-8 text-slate-700 mx-auto mb-2" />
                <p className="text-slate-500 text-sm">Sin API keys</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function NewInstitutionModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ name: '', email: '', contact_name: '', phone: '', plan: 'basic' })

  const mut = useMutation({
    mutationFn: () => createInstitution(form),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['institutions'] }); onClose() },
  })

  const fieldLabels: Record<string, string> = {
    name: 'Nombre',
    email: 'Email',
    contact_name: 'Nombre de contacto',
    phone: 'Teléfono',
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 rounded-2xl border border-slate-800 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-800">
          <h3 className="text-white font-semibold">Nueva institución</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1.5 rounded-lg transition-colors cursor-pointer"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 space-y-3">
          {(['name', 'email', 'contact_name', 'phone'] as const).map((field) => (
            <div key={field}>
              <label className="text-slate-300 text-xs font-medium mb-1.5 block">
                {fieldLabels[field]}
              </label>
              <input
                value={form[field]}
                onChange={(e) => setForm({ ...form, [field]: e.target.value })}
                className={inputClass}
              />
            </div>
          ))}
          <div>
            <label className="text-slate-300 text-xs font-medium mb-1.5 block">Plan</label>
            <select
              value={form.plan}
              onChange={(e) => setForm({ ...form, plan: e.target.value })}
              className={`${inputClass} cursor-pointer`}
            >
              {['basic', 'standard', 'premium', 'enterprise'].map((p) => (
                <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
              ))}
            </select>
          </div>
          <button
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !form.name || !form.email}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white py-2.5 rounded-xl text-sm font-medium transition-colors mt-1 cursor-pointer"
          >
            {mut.isPending ? 'Creando...' : 'Crear institución'}
          </button>
          {mut.isError && <p className="text-red-400 text-xs">{(mut.error as any)?.response?.data?.detail || 'Error al crear'}</p>}
        </div>
      </div>
    </div>
  )
}

export default function Institutions() {
  const [showNew, setShowNew] = useState(false)
  const [keysFor, setKeysFor] = useState<any | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['institutions'],
    queryFn: () => getInstitutions(),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white text-xl font-semibold">Instituciones</h2>
          <p className="text-slate-400 text-sm mt-1">Clientes que consumen SarEmi API</p>
        </div>
        <button
          onClick={() => setShowNew(true)}
          className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-xl text-sm flex items-center gap-2 transition-colors cursor-pointer"
        >
          <Plus className="w-4 h-4" /> Nueva institución
        </button>
      </div>

      {isLoading ? (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700/60 overflow-hidden animate-pulse">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-4 border-b border-slate-700/40 last:border-0">
              <div className="h-4 w-40 bg-slate-700 rounded" />
              <div className="h-4 w-36 bg-slate-700 rounded" />
              <div className="h-5 w-16 bg-slate-700 rounded ml-auto" />
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-slate-800/50 rounded-xl border border-slate-700/60 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/60 bg-slate-900/30">
                {['Nombre', 'Email', 'Plan', 'API Keys', 'Estado', 'Creada', ''].map((h) => (
                  <th key={h} className="text-left text-slate-500 font-medium text-xs uppercase tracking-wider px-4 py-3">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/40">
              {data?.data?.map((inst: any) => (
                <tr key={inst.id} className="hover:bg-slate-700/30 transition-colors group">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-7 h-7 rounded-lg bg-blue-600/15 flex items-center justify-center shrink-0">
                        <Building2 className="w-3.5 h-3.5 text-blue-400" />
                      </div>
                      <span className="text-white font-medium">{inst.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-xs">{inst.email}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs bg-slate-700/60 text-slate-300 px-2.5 py-0.5 rounded-full capitalize">
                      {inst.plan}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-300 tabular-nums">{inst.api_keys_count ?? 0}</td>
                  <td className="px-4 py-3"><Badge active={inst.active} /></td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{formatDate(inst.created_at)}</td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setKeysFor(inst)}
                      className="text-slate-500 hover:text-blue-400 transition-colors p-1 rounded cursor-pointer opacity-0 group-hover:opacity-100"
                      title="Gestionar API Keys"
                    >
                      <Key className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
              {data?.data?.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center">
                    <div className="flex flex-col items-center gap-2">
                      <Building2 className="w-8 h-8 text-slate-700" />
                      <p className="text-slate-500 text-sm">Sin instituciones</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showNew && <NewInstitutionModal onClose={() => setShowNew(false)} />}
      {keysFor && <ApiKeysModal institution={keysFor} onClose={() => setKeysFor(null)} />}
    </div>
  )
}
