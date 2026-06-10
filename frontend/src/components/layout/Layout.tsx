import { type ReactNode } from 'react'
import Sidebar from './Sidebar'
import { useAuth } from '../../hooks/useAuth'

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()

  return (
    <div className="flex min-h-screen bg-slate-900">
      <Sidebar onLogout={logout} userName={user?.email} />
      <main className="flex-1 overflow-auto">
        <div className="p-6 max-w-7xl mx-auto">{children}</div>
      </main>
    </div>
  )
}
