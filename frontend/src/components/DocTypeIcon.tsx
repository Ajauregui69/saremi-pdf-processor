import { CreditCard, FileText, Landmark, Home, Briefcase, Receipt, FileCheck, DollarSign, Clipboard, HelpCircle } from 'lucide-react'

const ICON_MAP: Record<string, React.ElementType> = {
  ine: CreditCard,
  curp: FileText,
  bank_statement: Landmark,
  proof_of_address: Home,
  payroll: Briefcase,
  tax_return: Receipt,
  employment_letter: FileCheck,
  income_proof: DollarSign,
  document: Clipboard,
  unknown: HelpCircle,
}

export default function DocTypeIcon({ type, className = 'w-4 h-4' }: { type?: string; className?: string }) {
  const Icon = (type && ICON_MAP[type]) || Clipboard
  return <Icon className={className} />
}
