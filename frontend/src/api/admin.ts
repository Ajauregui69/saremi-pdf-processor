import { api } from './client'

// ── Auth ──────────────────────────────────────────────────────────────────────
export const login = (email: string, password: string) =>
  api.post('/admin/auth/login', { email, password }).then((r) => r.data)

// ── Stats ─────────────────────────────────────────────────────────────────────
export const getStats = () => api.get('/admin/stats').then((r) => r.data)

// ── Institutions ──────────────────────────────────────────────────────────────
export const getInstitutions = (params?: { page?: number; limit?: number; active?: boolean }) =>
  api.get('/admin/institutions', { params }).then((r) => r.data)

export const getInstitution = (id: string) =>
  api.get(`/admin/institutions/${id}`).then((r) => r.data)

export const createInstitution = (data: {
  name: string; email: string; contact_name?: string
  phone?: string; plan?: string; baas_entity_id?: string
}) => api.post('/admin/institutions', data).then((r) => r.data)

export const updateInstitution = (id: string, data: Record<string, unknown>) =>
  api.patch(`/admin/institutions/${id}`, data).then((r) => r.data)

export const deleteInstitution = (id: string) =>
  api.delete(`/admin/institutions/${id}`)

// ── API Keys ──────────────────────────────────────────────────────────────────
export const getApiKeys = (institutionId: string) =>
  api.get(`/admin/institutions/${institutionId}/api-keys`).then((r) => r.data)

export const createApiKey = (institutionId: string, data: { label?: string; expires_at?: string }) =>
  api.post(`/admin/institutions/${institutionId}/api-keys`, data).then((r) => r.data)

export const revokeApiKey = (institutionId: string, keyId: string) =>
  api.delete(`/admin/institutions/${institutionId}/api-keys/${keyId}`)

// ── Verifications ─────────────────────────────────────────────────────────────
export const getVerifications = (params?: {
  page?: number; limit?: number
  institution_id?: string; document_type?: string; status?: string
}) => api.get('/admin/verifications', { params }).then((r) => r.data)

export const getVerification = (id: string) =>
  api.get(`/admin/verifications/${id}`).then((r) => r.data)

export const deleteVerification = (id: string) =>
  api.delete(`/admin/verifications/${id}`)

export const reverifyVerification = (id: string) =>
  api.post(`/admin/verifications/${id}/reverify`).then((r) => r.data)

export const cancelProcessing = (id: string) =>
  api.post(`/admin/verifications/${id}/cancel`).then((r) => r.data)

// ── Person Groups ─────────────────────────────────────────────────────────────
export const getPersonGroups = (params?: { page?: number; limit?: number }) =>
  api.get('/admin/person-groups', { params }).then((r) => r.data)

export const getPersonGroup = (id: string) =>
  api.get(`/admin/person-groups/${id}`).then((r) => r.data)

export const createPersonGroup = (data: { name: string; notes?: string; institution_id?: string; verification_ids: string[] }) =>
  api.post('/admin/person-groups', data).then((r) => r.data)

export const deletePersonGroup = (id: string) =>
  api.delete(`/admin/person-groups/${id}`)

export const updateGroupMembers = (groupId: string, add: string[], remove: string[]) =>
  api.patch(`/admin/person-groups/${groupId}/members`, { add, remove }).then((r) => r.data)

// ── Manual Reviews ────────────────────────────────────────────────────────────
export const getManualReviews = (params?: { resolved?: boolean; page?: number; limit?: number }) =>
  api.get('/admin/manual-reviews', { params }).then((r) => r.data)

export const resolveReview = (id: string, decision: 'approved' | 'rejected', notes?: string) =>
  api.patch(`/admin/manual-reviews/${id}`, { decision, notes }).then((r) => r.data)
