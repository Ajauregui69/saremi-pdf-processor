import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleString('es-MX', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function formatDateShort(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('es-MX', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

export const STATUS_COLORS: Record<string, string> = {
  processing:    'bg-slate-700/50 text-slate-300 ring-1 ring-slate-600/40',
  verified:      'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/25',
  invalid:       'bg-red-500/15 text-red-400 ring-1 ring-red-500/25',
  inconclusive:  'bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/25',
  manual_review: 'bg-orange-500/15 text-orange-400 ring-1 ring-orange-500/25',
}

export const STATUS_DOT: Record<string, string> = {
  processing:    'bg-slate-400',
  verified:      'bg-emerald-400',
  invalid:       'bg-red-400',
  inconclusive:  'bg-amber-400',
  manual_review: 'bg-orange-400',
}

export const STATUS_LABELS: Record<string, string> = {
  processing:    'Analizando...',
  verified:      'Verificado',
  invalid:       'Inválido',
  inconclusive:  'Inconcluso',
  manual_review: 'Revisión Manual',
}

export const DOC_TYPE_LABELS: Record<string, string> = {
  ine:               'INE',
  curp:              'CURP',
  bank_statement:    'Estado de Cuenta',
  proof_of_address:  'Comprobante de Domicilio',
  payroll:           'Recibo de Nómina',
  tax_return:        'Declaración Fiscal',
  employment_letter: 'Carta Laboral',
  income_proof:      'Comprobante de Ingresos',
  document:          'Documento General',
  unknown:           'Tipo Desconocido',
}

export const DOC_TYPE_ICONS: Record<string, string> = {
  ine:               '🪪',
  curp:              '📄',
  bank_statement:    '🏦',
  proof_of_address:  '🏠',
  payroll:           '💼',
  tax_return:        '🧾',
  employment_letter: '📝',
  income_proof:      '💰',
  document:          '📋',
  unknown:           '❓',
}
