import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { CheckCircle2, KeyRound, Mail, ShieldAlert, Sparkles, Unlink } from 'lucide-react'
import { apiClient } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import type { Preferences } from '../types'

const ALL_SOURCES = [
  { id: 'remotive', label: 'Remotive Public API' },
  { id: 'arbeitnow', label: 'Arbeitnow Public API' },
  { id: 'manual', label: 'Manual URL Import' },
]

export function SettingsPage() {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const gmailCallback = searchParams.get('gmail')
  const gmailReason = searchParams.get('reason')

  const { data: authStatus, isLoading: loadingAuth } = useQuery({
    queryKey: ['auth-status'],
    queryFn: apiClient.getAuthStatus,
  })

  const { data: profile } = useQuery({
    queryKey: ['profile'],
    queryFn: apiClient.getProfile,
  })

  const [tone, setTone] = useState<'formal' | 'friendly' | 'concise'>('formal')
  const [sources, setSources] = useState<string[]>(['remotive', 'manual'])
  const [targetRoles, setTargetRoles] = useState('')
  const [preferredLocations, setPreferredLocations] = useState('')
  const [remotePref, setRemotePref] = useState<'remote' | 'hybrid' | 'onsite' | 'any'>('any')
  const [feedback, setFeedback] = useState<string | null>(null)
  const [groqResult, setGroqResult] = useState<string | null>(null)

  useEffect(() => {
    if (profile?.preferences) {
      setTone(profile.preferences.cover_letter_tone || 'formal')
      setSources(profile.preferences.job_sources || ['remotive', 'manual'])
      setTargetRoles((profile.preferences.target_roles || []).join(', '))
      setPreferredLocations((profile.preferences.preferred_locations || []).join(', '))
      setRemotePref(profile.preferences.remote_preference || 'any')
    }
  }, [profile])

  const connectGoogleMutation = useMutation({
    mutationFn: apiClient.startGoogleAuth,
    onSuccess: (res) => {
      window.location.href = res.auth_url
    },
    onError: (err: Error) => {
      setFeedback(err.message)
    },
  })

  const disconnectGoogleMutation = useMutation({
    mutationFn: apiClient.disconnectGoogleAuth,
    onSuccess: (updated) => {
      queryClient.setQueryData(['auth-status'], updated)
      setFeedback('Gmail disconnected.')
    },
  })

  const testGroqMutation = useMutation({
    mutationFn: apiClient.testGroq,
    onSuccess: (res) => {
      setGroqResult(
        res.ok
          ? `Connected (${res.model}, ${res.latency_ms ?? 0} ms): "${res.message}"`
          : `Not ready: ${res.message}`,
      )
    },
    onError: (err: Error) => setGroqResult(err.message),
  })

  const savePrefsMutation = useMutation({
    mutationFn: (prefs: Preferences) => apiClient.updateProfile({ preferences: prefs }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['profile'], updated)
      setFeedback('Copilot preferences saved.')
    },
    onError: (err: Error) => setFeedback(err.message),
  })

  const toggleSource = (id: string) => {
    setSources((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]))
  }

  const handleSavePreferences = () => {
    if (!profile) return
    const nextPrefs: Preferences = {
      ...profile.preferences,
      cover_letter_tone: tone,
      job_sources: sources,
      remote_preference: remotePref,
      target_roles: targetRoles
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      preferred_locations: preferredLocations
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    }
    savePrefsMutation.mutate(nextPrefs)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Configure Gmail OAuth2 (read + draft only), inspect Groq LLM readiness, and set copilot defaults."
      />

      {gmailCallback === 'connected' && (
        <div className="rounded-xl border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/40 p-4 text-sm text-emerald-800 dark:text-emerald-200 flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4" /> Gmail OAuth2 connected successfully.
        </div>
      )}
      {gmailCallback === 'error' && (
        <div className="rounded-xl border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/40 p-4 text-sm text-rose-800 dark:text-rose-200 flex items-center gap-2">
          <ShieldAlert className="h-4 w-4" /> Gmail OAuth failed: {gmailReason || 'Unknown error'}
        </div>
      )}
      {feedback && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4 text-sm">
          {feedback}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Gmail OAuth Card */}
        <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <Mail className="h-5 w-5 text-brand-600 dark:text-indigo-400" />
              <h3 className="text-base font-semibold">Gmail Integration</h3>
            </div>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                authStatus?.gmail_connected
                  ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                  : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
              }`}
            >
              {loadingAuth ? 'Checking...' : authStatus?.gmail_connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>

          <p className="text-xs text-slate-500 dark:text-slate-400">
            Least-privilege scopes: <code>gmail.readonly</code> and <code>gmail.compose</code>. Copilot saves drafts for your review and never auto-sends emails.
          </p>

          {authStatus?.gmail_email && (
            <div className="rounded-lg bg-slate-50 dark:bg-slate-800/70 px-3 py-2 text-xs">
              Connected account: <span className="font-semibold">{authStatus.gmail_email}</span>
            </div>
          )}

          {!authStatus?.google_oauth_configured && (
            <div className="rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/30 p-3 text-xs text-amber-800 dark:text-amber-200">
              Set <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> in your <code>.env</code> file to enable OAuth login.
            </div>
          )}

          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => connectGoogleMutation.mutate()}
              disabled={connectGoogleMutation.isPending || !authStatus?.google_oauth_configured}
              className="rounded-lg bg-zinc-900 dark:bg-zinc-100 px-4 py-2 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-50"
            >
              {authStatus?.gmail_connected ? 'Reconnect Gmail' : 'Connect Gmail'}
            </button>
            {authStatus?.gmail_connected && (
              <button
                type="button"
                onClick={() => disconnectGoogleMutation.mutate()}
                disabled={disconnectGoogleMutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <Unlink className="h-4 w-4" /> Disconnect
              </button>
            )}
          </div>
        </section>

        {/* Groq LLM Status Card */}
        <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <KeyRound className="h-5 w-5 text-brand-600 dark:text-indigo-400" />
              <h3 className="text-base font-semibold">Groq LLM Configuration</h3>
            </div>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                authStatus?.groq_configured
                  ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                  : 'bg-amber-50 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300'
              }`}
            >
              {authStatus?.groq_configured ? 'Key Configured' : 'Key Missing'}
            </span>
          </div>

          <div className="rounded-lg bg-slate-50 dark:bg-slate-800/70 p-3 text-xs space-y-1">
            <div>
              Active Model: <span className="font-mono font-semibold">{authStatus?.groq_model ?? 'llama-3.3-70b-versatile'}</span>
            </div>
            <div className="text-slate-500 dark:text-slate-400">
              Secrets are loaded strictly from environment variables (<code>GROQ_API_KEY</code>, <code>GROQ_MODEL</code>).
            </div>
          </div>

          <button
            type="button"
            onClick={() => testGroqMutation.mutate()}
            disabled={testGroqMutation.isPending}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 dark:border-slate-700 px-4 py-2 text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <Sparkles className="h-4 w-4 text-brand-600" />
            {testGroqMutation.isPending ? 'Testing Groq...' : 'Test Groq Connection'}
          </button>

          {groqResult && <p className="text-xs text-slate-600 dark:text-slate-300">{groqResult}</p>}
        </section>
      </div>

      {/* Preferences Card */}
      <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-5">
        <h3 className="text-base font-semibold">Copilot Defaults</h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">
              Target Roles (comma-separated)
            </label>
            <input
              value={targetRoles}
              onChange={(e) => setTargetRoles(e.target.value)}
              placeholder="Backend Engineer, AI Engineer, Full Stack"
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">
              Preferred Locations (comma-separated)
            </label>
            <input
              value={preferredLocations}
              onChange={(e) => setPreferredLocations(e.target.value)}
              placeholder="Remote, San Francisco, New York"
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">
              Cover Letter Tone
            </label>
            <select
              value={tone}
              onChange={(e) => setTone(e.target.value as 'formal' | 'friendly' | 'concise')}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm"
            >
              <option value="formal">Formal</option>
              <option value="friendly">Friendly</option>
              <option value="concise">Concise</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">
              Remote Preference
            </label>
            <select
              value={remotePref}
              onChange={(e) => setRemotePref(e.target.value as 'remote' | 'hybrid' | 'onsite' | 'any')}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm"
            >
              <option value="any">Any</option>
              <option value="remote">Remote Only</option>
              <option value="hybrid">Hybrid</option>
              <option value="onsite">On-site</option>
            </select>
          </div>
        </div>

        <div>
          <span className="block text-xs font-medium text-slate-500 mb-2">Job Discovery Sources</span>
          <div className="flex flex-wrap gap-3">
            {ALL_SOURCES.map((src) => (
              <label key={src.id} className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={sources.includes(src.id)}
                  onChange={() => toggleSource(src.id)}
                  className="rounded border-slate-300 text-brand-600"
                />
                {src.label}
              </label>
            ))}
          </div>
        </div>

        <button
          type="button"
          onClick={handleSavePreferences}
          disabled={savePrefsMutation.isPending || !profile}
          className="rounded-lg bg-zinc-900 dark:bg-zinc-100 px-4 py-2 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-50"
        >
          {savePrefsMutation.isPending ? 'Saving...' : 'Save Preferences'}
        </button>
      </section>
    </div>
  )
}
