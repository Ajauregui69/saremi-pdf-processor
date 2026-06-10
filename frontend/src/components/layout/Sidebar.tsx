import { LayoutDashboard, Building2, ShieldCheck, ClipboardList, Users, LogOut, Shield } from 'lucide-react'
import { cn } from '../../lib/utils'

const navItems = [
  { label: 'Dashboard',       icon: LayoutDashboard, href: '/' },
  { label: 'Instituciones',   icon: Building2,        href: '/institutions' },
  { label: 'Verificaciones',  icon: ShieldCheck,      href: '/verifications' },
  { label: 'Personas',        icon: Users,            href: '/groups' },
  { label: 'Revisión Manual', icon: ClipboardList,    href: '/manual-review' },
]

interface SidebarProps {
  onLogout: () => void
  userName?: string
}

export default function Sidebar({ onLogout, userName }: SidebarProps) {
  const current = window.location.pathname
  const initial = (userName || 'A')[0].toUpperCase()

  return (
    <aside className="w-56 shrink-0 bg-slate-950 border-r border-slate-800/70 flex flex-col min-h-screen">
      {/* Brand */}
      <div className="px-4 py-5 border-b border-slate-800/70">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shrink-0 shadow-lg shadow-blue-600/25">
            <Shield className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-white font-semibold text-sm leading-none tracking-tight">SarEmi</h1>
            <p className="text-slate-500 text-xs mt-0.5">DocVerify Admin</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        <p className="text-slate-600 text-[10px] font-semibold px-3 pb-2 uppercase tracking-widest">Navegación</p>
        {navItems.map((item) => {
          const active = current === item.href || (item.href !== '/' && current.startsWith(item.href))
          return (
            <a
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all duration-150 relative',
                active
                  ? 'bg-blue-600/12 text-blue-400 font-medium'
                  : 'text-slate-500 hover:text-slate-200 hover:bg-slate-800/60'
              )}
            >
              {active && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-blue-500 rounded-r-full" />
              )}
              <item.icon className={cn(
                'w-4 h-4 shrink-0 transition-colors',
                active ? 'text-blue-400' : 'text-slate-600 group-hover:text-slate-400'
              )} />
              {item.label}
            </a>
          )
        })}
      </nav>

      {/* User */}
      <div className="px-3 py-3 border-t border-slate-800/70">
        <div className="flex items-center gap-2.5 px-3 py-2 mb-1">
          <div className="w-6 h-6 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center shrink-0">
            <span className="text-slate-300 text-[10px] font-semibold">{initial}</span>
          </div>
          <p className="text-slate-400 text-xs truncate flex-1">{userName || 'Administrador'}</p>
        </div>
        <button
          onClick={onLogout}
          className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-slate-500 hover:text-slate-200 hover:bg-slate-800/60 w-full transition-all duration-150 cursor-pointer"
        >
          <LogOut className="w-4 h-4 shrink-0" />
          Cerrar sesión
        </button>
      </div>
    </aside>
  )
}
