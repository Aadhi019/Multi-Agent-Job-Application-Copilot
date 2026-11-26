import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Link2,
  MapPin,
  Search,
} from 'lucide-react'
import { apiClient } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import type { Job } from '../types'

function fitColor(score: number | null): string {
  if (score === null) return 'text-zinc-400'
  if (score >= 75) return 'text-emerald-600 dark:text-emerald-400'
  if (score >= 50) return 'text-zinc-900 dark:text-zinc-100'
  return 'text-zinc-500'
}

export function JobsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [query, setQuery] = useState('')
  const [locationFilter, setLocationFilter] = useState('')
  const [minScore, setMinScore] = useState<number>(0)
  const [sourceFilter, setSourceFilter] = useState<string>('')
  const [searchTerm, setSearchTerm] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const [showImport, setShowImport] = useState(false)
  const [importUrl, setImportUrl] = useState('')
  const [importTitle, setImportTitle] = useState('')
  const [importCompany, setImportCompany] = useState('')
  const [importDescription, setImportDescription] = useState('')
  const [banner, setBanner] = useState<string | null>(null)
  const [applyingJobId, setApplyingJobId] = useState<string | null>(null)

  const { data: jobs = [], isLoading, isError, error } = useQuery({
    queryKey: ['jobs', minScore, sourceFilter, searchTerm],
    queryFn: () =>
      apiClient.listJobs({
        min_score: minScore || undefined,
        source: sourceFilter || undefined,
        search: searchTerm || undefined,
      }),
  })

  const discoverMutation = useMutation({
    mutationFn: () =>
      apiClient.discoverJobs({
        query,
        location: locationFilter,
        sources: ['himalayas', 'jobicy', 'remotive', 'arbeitnow'],
        limit: 12,
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      setBanner(
        `Added ${res.discovered_count} roles (${res.deduplicated_count} duplicates skipped).`,
      )
    },
    onError: (err: Error) => setBanner(`Discovery error: ${err.message}`),
  })

  const importMutation = useMutation({
    mutationFn: () =>
      apiClient.importJobUrl({
        url: importUrl,
        title: importTitle || undefined,
        company: importCompany || undefined,
        description: importDescription || undefined,
      }),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      setShowImport(false)
      setImportUrl('')
      setImportTitle('')
      setImportCompany('')
      setImportDescription('')
      setBanner(`Imported "${job.title}" at ${job.company}.`)
    },
    onError: (err: Error) => setBanner(`Import error: ${err.message}`),
  })

  const applyMutation = useMutation({
    mutationFn: (job: Job) => {
      setApplyingJobId(job.id)
      return apiClient.createApplication(job.id)
    },
    onSuccess: (app) => {
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      navigate(`/applications/${app.id}`)
    },
    onSettled: () => setApplyingJobId(null),
    onError: (err: Error) => setBanner(`Failed to start workflow: ${err.message}`),
  })

  const rescoreMutation = useMutation({
    mutationFn: () => apiClient.rescoreJobs(true),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      setBanner(`Re-scored ${updated.length} saved job(s) against your latest profile.`)
    },
    onError: (err: Error) => setBanner(`Re-score error: ${err.message}`),
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <PageHeader
          title="Jobs"
          description="Live listings scored against your verified profile. Start a tailored workflow on any role."
        />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => rescoreMutation.mutate()}
            disabled={rescoreMutation.isPending || jobs.length === 0}
            className="inline-flex items-center justify-center rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-[13px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-50 transition-colors"
          >
            {rescoreMutation.isPending ? 'Re-scoring...' : 'Re-score Jobs'}
          </button>
          <button
            type="button"
            onClick={() => setShowImport((v) => !v)}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-[13px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
          >
            <Link2 className="h-3.5 w-3.5" />
            <span>Import URL</span>
          </button>
        </div>
      </div>

      {banner && (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-4 py-2.5 text-[13px] text-zinc-700 dark:text-zinc-300">
          {banner}
        </div>
      )}

      {showImport && (
        <section className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 space-y-3">
          <h2 className="text-sm font-semibold">Import Job by URL</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
            <input
              value={importUrl}
              onChange={(e) => setImportUrl(e.target.value)}
              placeholder="https://company.com/careers/role"
              className="sm:col-span-3 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-2 text-[13px]"
            />
            <input
              value={importTitle}
              onChange={(e) => setImportTitle(e.target.value)}
              placeholder="Title (optional)"
              className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-2 text-[13px]"
            />
            <input
              value={importCompany}
              onChange={(e) => setImportCompany(e.target.value)}
              placeholder="Company (optional)"
              className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-2 text-[13px]"
            />
            <button
              type="button"
              onClick={() => importMutation.mutate()}
              disabled={!importUrl.trim() || importMutation.isPending}
              className="rounded-lg bg-zinc-900 dark:bg-zinc-100 px-4 py-2 text-[13px] font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-50"
            >
              {importMutation.isPending ? 'Importing...' : 'Import & Score'}
            </button>
          </div>
          <textarea
            rows={3}
            value={importDescription}
            onChange={(e) => setImportDescription(e.target.value)}
            placeholder="Optional: paste job description if the site requires authentication..."
            className="w-full rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-2 text-[13px]"
          />
        </section>
      )}

      {/* Search & Filter Toolbar */}
      <section className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 p-4 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-12 gap-2.5">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Role or keyword (e.g. Python, Backend)"
            className="sm:col-span-5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-2 text-[13px]"
          />
          <input
            value={locationFilter}
            onChange={(e) => setLocationFilter(e.target.value)}
            placeholder="Location (e.g. India, Remote)"
            className="sm:col-span-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-2 text-[13px]"
          />
          <button
            type="button"
            onClick={() => discoverMutation.mutate()}
            disabled={discoverMutation.isPending}
            className="sm:col-span-3 rounded-lg bg-zinc-900 dark:bg-zinc-100 px-4 py-2 text-[13px] font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-60 transition-colors"
          >
            {discoverMutation.isPending ? 'Searching...' : 'Discover Jobs'}
          </button>
        </div>

        <div className="pt-3 border-t border-zinc-100 dark:border-zinc-800 flex flex-wrap items-center gap-2.5">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="h-3.5 w-3.5 text-zinc-400 absolute left-3 top-2.5" />
            <input
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Filter list..."
              className="w-full rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent pl-8 pr-3 py-1.5 text-xs"
            />
          </div>
          <select
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-2.5 py-1.5 text-xs"
          >
            <option value={0}>All scores</option>
            <option value={50}>Score ≥ 50</option>
            <option value={70}>Score ≥ 70</option>
            <option value={85}>Score ≥ 85</option>
          </select>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-2.5 py-1.5 text-xs"
          >
            <option value="">All sources</option>
            <option value="himalayas">Himalayas</option>
            <option value="jobicy">Jobicy</option>
            <option value="remotive">Remotive</option>
            <option value="arbeitnow">Arbeitnow</option>
            <option value="manual_url">Imported URL</option>
          </select>
        </div>
      </section>

      {isLoading && (
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 divide-y divide-zinc-100 dark:divide-zinc-800">
          {[1, 2, 3].map((i) => (
            <div key={i} className="p-5 h-24 animate-pulse" />
          ))}
        </div>
      )}

      {isError && (
        <div className="rounded-lg border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/30 p-4 text-xs text-rose-700">
          {(error as Error).message}
        </div>
      )}

      {!isLoading && jobs.length === 0 && (
        <div className="rounded-xl border border-dashed border-zinc-300 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-12 text-center space-y-1.5">
          <p className="text-sm font-medium">No jobs in your feed</p>
          <p className="text-xs text-zinc-500">
            Run Discover Jobs above or import a specific posting URL.
          </p>
        </div>
      )}

      {jobs.length > 0 && (
        <div className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 divide-y divide-zinc-200/70 dark:divide-zinc-800/70">
          {jobs.map((job) => {
            const isExpanded = expandedId === job.id
            const initial = (job.company || '?').slice(0, 1).toUpperCase()
            return (
              <article
                key={job.id}
                className="p-5 hover:bg-zinc-50/70 dark:hover:bg-zinc-800/30 transition-colors"
              >
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
                  <div className="flex items-start gap-3.5 flex-1 min-w-0">
                    <div className="hidden sm:flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-xs font-semibold text-zinc-700 dark:text-zinc-200 mt-0.5">
                      {initial}
                    </div>

                    <div className="space-y-1.5 flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                        <h3 className="text-sm font-semibold text-zinc-950 dark:text-white">
                          {job.title}
                        </h3>
                        <span className="text-xs text-zinc-400">•</span>
                        <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
                          {job.company}
                        </span>
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
                        <span className="inline-flex items-center gap-1">
                          <MapPin className="h-3 w-3" />
                          {job.location || 'Unspecified'}
                        </span>
                        <span className="uppercase tracking-wider text-[10px] font-medium text-zinc-400">
                          {job.source}
                        </span>
                        <a
                          href={job.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 hover:text-zinc-900 dark:hover:text-white"
                        >
                          Source <ExternalLink className="h-3 w-3" />
                        </a>
                        {job.description && (
                          <button
                            type="button"
                            onClick={() => setExpandedId(isExpanded ? null : job.id)}
                            className="inline-flex items-center gap-1 hover:text-zinc-900 dark:hover:text-white"
                          >
                            {isExpanded ? (
                              <>
                                Less <ChevronUp className="h-3 w-3" />
                              </>
                            ) : (
                              <>
                                Details <ChevronDown className="h-3 w-3" />
                              </>
                            )}
                          </button>
                        )}
                      </div>

                      {job.fit_reason && (
                        <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400 pt-0.5">
                          {job.fit_reason}
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center justify-between md:justify-end gap-4 shrink-0">
                    <div className="text-right">
                      <div className={`text-sm font-semibold tabular-nums ${fitColor(job.fit_score)}`}>
                        {job.fit_score !== null ? `${Math.round(job.fit_score)}%` : '—'}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider text-zinc-400">Match</div>
                    </div>

                    <button
                      type="button"
                      onClick={() => applyMutation.mutate(job)}
                      disabled={applyingJobId === job.id}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3.5 py-2 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-60 transition-colors"
                    >
                      <span>{applyingJobId === job.id ? 'Preparing...' : 'Apply'}</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                {isExpanded && job.description && (
                  <div className="mt-4 sm:ml-12 pt-3 border-t border-zinc-100 dark:border-zinc-800 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400 max-h-52 overflow-y-auto whitespace-pre-wrap">
                    {job.description}
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}
