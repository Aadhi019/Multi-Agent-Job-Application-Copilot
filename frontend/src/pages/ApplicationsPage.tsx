import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { apiClient } from '../api/client'
import { PageHeader } from '../components/PageHeader'

function statusDot(status: string): string {
  switch (status) {
    case 'awaiting_approval':
      return 'bg-amber-500'
    case 'ready_to_submit':
    case 'applied':
    case 'offer':
      return 'bg-emerald-500'
    case 'rejected':
      return 'bg-rose-500'
    default:
      return 'bg-zinc-400'
  }
}

export function ApplicationsPage() {
  const { data: apps = [], isLoading, isError, error } = useQuery({
    queryKey: ['applications'],
    queryFn: apiClient.listApplications,
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Applications"
        description="Review tailored documents, inspect form screenshots, and approve or reject checkpoints."
      />

      {isLoading && (
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 divide-y divide-zinc-100 dark:divide-zinc-800">
          {[1, 2].map((i) => (
            <div key={i} className="p-5 h-20 animate-pulse" />
          ))}
        </div>
      )}

      {isError && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
          {(error as Error).message}
        </div>
      )}

      {!isLoading && apps.length === 0 && (
        <div className="rounded-xl border border-dashed border-zinc-300 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-12 text-center space-y-3">
          <p className="text-sm font-medium">No applications yet</p>
          <p className="text-xs text-zinc-500">
            Open Jobs and click Apply on any listing to start a tailored workflow.
          </p>
          <Link
            to="/jobs"
            className="inline-flex items-center rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3.5 py-2 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200"
          >
            Browse Jobs
          </Link>
        </div>
      )}

      {apps.length > 0 && (
        <div className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 divide-y divide-zinc-200/70 dark:divide-zinc-800/70">
          {apps.map((app) => (
            <Link
              key={app.id}
              to={`/applications/${app.id}`}
              className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-5 hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition-colors"
            >
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2.5">
                  <span className="text-sm font-semibold text-zinc-950 dark:text-white">
                    {app.job_title}
                  </span>
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 dark:border-zinc-700 px-2 py-0.5 text-[11px] font-medium capitalize text-zinc-700 dark:text-zinc-300">
                    <span className={`h-1.5 w-1.5 rounded-full ${statusDot(app.status)}`} />
                    {app.status.replace(/_/g, ' ')}
                  </span>
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {app.company} • {app.location || 'Unspecified'} • Updated{' '}
                  {new Date(app.updated_at).toLocaleString()}
                </p>
              </div>
              <span className="inline-flex items-center gap-1 text-xs font-medium text-zinc-700 dark:text-zinc-300">
                Open workspace <ArrowRight className="h-3.5 w-3.5" />
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
