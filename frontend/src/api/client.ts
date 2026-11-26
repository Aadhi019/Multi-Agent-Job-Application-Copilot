import type {
  AgentRunItem,
  AnalyticsSummary,
  ApplicationDetail,
  ApplicationSummary,
  AuthStatus,
  DocumentItem,
  DocumentVerification,
  EmailRecord,
  FormFillReport,
  GoogleAuthStart,
  GroqTestResult,
  HealthStatus,
  Job,
  JobDiscoveryPayload,
  JobDiscoveryResult,
  JobImportPayload,
  Profile,
  ProfileFact,
  ProfileUpdatePayload,
  ResumeBulletEvidence,
  ResumeUploadResponse,
  TrackerSyncResult,
} from '../types'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith('/api') ? `${API_BASE}${path}` : `${API_BASE}/api${path}`
  const isFormData = init?.body instanceof FormData
  const response = await fetch(url, {
    headers: isFormData
      ? init?.headers
      : {
          'Content-Type': 'application/json',
          ...(init?.headers ?? {}),
        },
    ...init,
  })

  if (!response.ok) {
    let detail = response.statusText
    try {
      const json = (await response.json()) as { detail?: string }
      if (json?.detail) detail = json.detail
    } catch {
      const text = await response.text()
      if (text) detail = text
    }
    throw new Error(detail || `API error (${response.status})`)
  }

  return (await response.json()) as T
}

export const apiClient = {
  getHealth: () => request<HealthStatus>('/api/health'),

  getProfile: () => request<Profile>('/api/profile'),
  updateProfile: (payload: ProfileUpdatePayload) =>
    request<Profile>('/api/profile', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  uploadResume: (file: File, autoPopulate = true) => {
    const form = new FormData()
    form.append('file', file)
    form.append('auto_populate', String(autoPopulate))
    return request<ResumeUploadResponse>('/api/profile/resume', {
      method: 'POST',
      body: form,
    })
  },

  getAuthStatus: () => request<AuthStatus>('/api/auth/status'),
  startGoogleAuth: () => request<GoogleAuthStart>('/api/auth/google', { method: 'POST' }),
  disconnectGoogleAuth: () =>
    request<AuthStatus>('/api/auth/google/disconnect', { method: 'POST' }),
  testGroq: () => request<GroqTestResult>('/api/auth/groq/test', { method: 'POST' }),

  listJobs: (params?: { min_score?: number; source?: string; search?: string }) => {
    const qs = new URLSearchParams()
    if (params?.min_score !== undefined && params.min_score > 0) {
      qs.set('min_score', String(params.min_score))
    }
    if (params?.source) qs.set('source', params.source)
    if (params?.search) qs.set('search', params.search)
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request<Job[]>(`/api/jobs${suffix}`)
  },
  discoverJobs: (payload: JobDiscoveryPayload) =>
    request<JobDiscoveryResult>('/api/jobs/discover', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  importJobUrl: (payload: JobImportPayload) =>
    request<Job>('/api/jobs/import-url', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  rescoreJobs: (useLlm = true) =>
    request<Job[]>(`/api/jobs/rescore?use_llm=${useLlm}`, { method: 'POST' }),

  listApplications: () => request<ApplicationSummary[]>('/api/applications'),
  createApplication: (jobId: string, coverLetterTone?: string) =>
    request<ApplicationDetail>('/api/applications', {
      method: 'POST',
      body: JSON.stringify({ job_id: jobId, cover_letter_tone: coverLetterTone }),
    }),
  getApplication: (id: string) => request<ApplicationDetail>(`/api/applications/${id}`),
  updateApplicationStatus: (id: string, status: string, notes?: string) =>
    request<ApplicationSummary>(`/api/applications/${id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status, notes }),
    }),
  updateCoverLetter: (id: string, content: string, tone?: string) =>
    request<DocumentItem>(`/api/applications/${id}/cover-letter`, {
      method: 'PUT',
      body: JSON.stringify({ content, tone }),
    }),
  approveApplication: (id: string, feedback = '') =>
    request<ApplicationDetail>(`/api/applications/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ feedback }),
    }),
  rejectApplication: (id: string, feedback = '') =>
    request<ApplicationDetail>(`/api/applications/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ feedback }),
    }),
  getResumeDownloadUrl: (id: string, format: 'docx' | 'pdf' | 'md') =>
    `${API_BASE}/api/applications/${id}/resume/download?format=${format}`,
  getScreenshotUrl: (relativePath: string) => `${API_BASE}${relativePath}`,

  runFormFill: (id: string, url?: string) =>
    request<FormFillReport>(`/api/applications/${id}/form-fill`, {
      method: 'POST',
      body: JSON.stringify({ url: url || null, headless: true }),
    }),
  draftFollowUp: (
    id: string,
    followupType: 'after_applying' | 'after_interview' | 'thank_you',
    toEmail = '',
    extraContext = '',
  ) =>
    request<DocumentItem>(`/api/applications/${id}/follow-up`, {
      method: 'POST',
      body: JSON.stringify({
        followup_type: followupType,
        to_email: toEmail,
        extra_context: extraContext,
      }),
    }),
  approveFollowUpDraft: (
    applicationId: string,
    docId: string,
    payload?: { to_email?: string; subject?: string; body?: string },
  ) =>
    request<DocumentItem>(`/api/applications/${applicationId}/follow-up/${docId}/approve-draft`, {
      method: 'POST',
      body: JSON.stringify(payload ?? {}),
    }),

  listEmails: () => request<EmailRecord[]>('/api/emails'),
  syncEmails: (query = '') =>
    request<TrackerSyncResult>('/api/emails/sync', {
      method: 'POST',
      body: JSON.stringify({ query }),
    }),

  runAgent: (agentName: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/agents/${agentName}/run`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listAgentRuns: (limit = 50) => request<AgentRunItem[]>(`/api/agent-runs?limit=${limit}`),
  getAnalyticsSummary: () => request<AnalyticsSummary>('/api/analytics/summary'),
  generateInterviewPrep: (id: string) =>
    request<DocumentItem>(`/api/applications/${id}/interview-prep`, { method: 'POST' }),

  getDocumentVerification: (documentId: string) =>
    request<DocumentVerification>(`/api/documents/${documentId}/verification`),
  regenerateBullet: (documentId: string, bulletId: string) =>
    request<ResumeBulletEvidence>(`/api/documents/${documentId}/bullets/${bulletId}/regenerate`, {
      method: 'POST',
    }),
  listProfileFacts: () => request<ProfileFact[]>('/api/profile/facts'),
  rebuildProfileFacts: () => request<ProfileFact[]>('/api/profile/facts/rebuild', { method: 'POST' }),
  createProfileFact: (payload: { category: string; text: string; source_section: string }) =>
    request<ProfileFact>('/api/profile/facts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateProfileFact: (factId: string, payload: { text?: string; category?: string; source_section?: string }) =>
    request<ProfileFact>(`/api/profile/facts/${factId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deleteProfileFact: async (factId: string) => {
    const url = `${API_BASE}/api/profile/facts/${factId}`
    const resp = await fetch(url, { method: 'DELETE' })
    if (!resp.ok) throw new Error(`API error (${resp.status})`)
  },

  getWsUrl: (runId: string) => {
    if (API_BASE) {
      return `${API_BASE.replace(/^http/, 'ws')}/ws/runs/${runId}`
    }
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/ws/runs/${runId}`
  },
}
