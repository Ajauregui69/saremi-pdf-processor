import { useAuth } from './hooks/useAuth'
import Layout from './components/layout/Layout'
import Login from './pages/Login'
import Dashboard from './pages/dashboard/Dashboard'
import Institutions from './pages/institutions/Institutions'
import Verifications from './pages/verifications/Verifications'
import ManualReview from './pages/manual-review/ManualReview'
import Groups from './pages/groups/Groups'

function Router() {
  const path = window.location.pathname

  if (path === '/institutions') return <Institutions />
  if (path === '/verifications') return <Verifications />
  if (path === '/manual-review') return <ManualReview />
  if (path === '/groups') return <Groups />
  return <Dashboard />
}

export default function App() {
  const { isAuthenticated } = useAuth()
  const path = window.location.pathname

  if (path === '/login' || !isAuthenticated) return <Login />

  return (
    <Layout>
      <Router />
    </Layout>
  )
}
