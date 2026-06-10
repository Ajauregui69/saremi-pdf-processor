import { useState } from 'react'

interface User {
  id: string
  email: string
  role: string
  fullName?: string
}

export function useAuth() {
  const [user, setUser] = useState<User | null>(() => {
    const stored = localStorage.getItem('saremi_user')
    return stored ? JSON.parse(stored) : null
  })

  const setSession = (token: string, userData: User) => {
    localStorage.setItem('saremi_token', token)
    localStorage.setItem('saremi_user', JSON.stringify(userData))
    setUser(userData)
  }

  const logout = () => {
    localStorage.removeItem('saremi_token')
    localStorage.removeItem('saremi_user')
    setUser(null)
    window.location.href = '/login'
  }

  const isAuthenticated = !!user && !!localStorage.getItem('saremi_token')

  return { user, isAuthenticated, setSession, logout }
}
