import axios from 'axios'

export const api = axios.create({ baseURL: '/' })

// Inyectar token en cada request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('saremi_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Redirigir a login si el token expiró
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('saremi_token')
      localStorage.removeItem('saremi_user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)
