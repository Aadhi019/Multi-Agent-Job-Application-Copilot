import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowUpRight } from 'lucide-react'
import { apiClient } from '../api/client'
import { PageHeader } from '../components/PageHeader'

const STATUS_ORDER = [
  'draft',
  'tailoring',
  'awaiting_approval',
  'ready_to_submit',
  'applied',
  'interview',
  'offer',
  'rejected',
]

function statusDot(status: string): string {
  switch (status) {
    case 'awaiting_approval':
      return 'bg-amber-500'
    case 'ready_to_submit':
    case 'applied':
      return 'bg-zinc-900 dark:bg-zinc-100'
    case 'interview':
    case 'offer':
      return 'bg-emerald-500'
    case 'rejected':
      return 'bg-rose-500'
    default:
      return 'bg-zinc-400'
  }
}

export function DashboardPage() {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: apiClient.getHealth,
  })

  const { data: analytics, isLoading, isError, error } = useQuery({
    queryKey: ['analytics-summary'],
    queryFn: apiClient.getAnalyticsSummary,
    refetchInterval: 15000,
  })

  const totalApps = analytics?.total_applications ?? 0
  const counts = analytics?.counts_by_status ?? {}
  const maxStatusCount = Math.max(1, ...Object.values(counts))

  const metrics = [
    {
      label: 'Discovered Jobs',
      value: String(analytics?.total_jobs ?? 0),
      note: 'Ranked by fit score',
    },
    {
      label: 'Applications',
      value: String(totalApps),
      note: `${counts.awaiting_approval ?? 0} awaiting review`,
    },
    {
      label: 'Response Rate',
      value: `${analytics?.response_rate ?? 0}%`,
      note: 'Replies / submitted',
    },
    {
      label: 'Avg Time / App',
      value:
        analytics?.avg_time_per_application_seconds !== null &&
        analytics?.avg_time_per_application_seconds !== undefined
          ? `${analytics.avg_time_per_application_seconds}s`
          : '—',
      note: 'Agent compute time',
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <PageHeader
          title="Overview"
          description="Application pipeline, response metrics, and agent execution telemetry."
        />
        <Link
          to="/jobs"
          className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3.5 py-2 text-[13px] font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 transition-colors"
        >
          <span>Discover Jobs</span>
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {isError && (
        <div className="rounded-lg border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/30 p-4 text-[13px] text-rose-700 dark:text-rose-300">
          Failed to load analytics: {(error as Error).message}
        </div>
      )}

      {/* Connected Metric Strip */}
      <section className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 overflow-hidden">
        <div className="grid grid-cols-2 lg:grid-cols-4 divide-y lg:divide-y-0 lg:divide-x divide-zinc-200/80 dark:divide-zinc-800/80">
          {metrics.map((m) => (
            <div key={m.label} className="p-5 space-y-1">
              <div className="text-[11px] font-medium uppercase tracking-[0.05em] text-zinc-500 dark:text-zinc-400">
                {m.label}
              </div>
              <div className="text-2xl font-semibold tracking-tight tabular-nums text-zinc-950 dark:text-white">
                {isLoading ? '—' : m.value}
              </div>
              <div className="text-xs text-zinc-500 dark:text-zinc-400">{m.note}</div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-950 dark:text-white">
              Pipeline by Stage
            </h2>
            <Link
              to="/applications"
              className="text-xs font-medium text-zinc-500 hover:text-zinc-950 dark:hover:text-white transition-colors"
            >
              View all →
            </Link>
          </div>

          {totalApps === 0 ? (
            <div className="py-8 text-center text-xs text-zinc-500">
              No applications yet. Open Jobs to start a tailored workflow.
            </div>
          ) : (
            <div className="space-y-3">
              {STATUS_ORDER.filter((s) => (counts[s] ?? 0) > 0).map((status) => {
                const count = counts[status] ?? 0
                const pct = Math.round((count / maxStatusCount) * 100)
                return (
                  <div key={status} className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="inline-flex items-center gap-2 font-medium capitalize text-zinc-700 dark:text-zinc-300">
                        <span className={`h-1.5 w-1.5 rounded-full ${statusDot(status)}`} />
                        {status.replace(/_/g, ' ')}
                      </span>
                      <span className="tabular-nums font-medium text-zinc-900 dark:text-zinc-100">
                        {count}
                      </span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-zinc-900 dark:bg-zinc-200 transition-all duration-300"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-950 dark:text-white">
              Agent Reliability
            </h2>
            <Link
              to="/agents"
              className="text-xs font-medium text-zinc-500 hover:text-zinc-950 dark:hover:text-white transition-colors"
            >
              Monitor →
            </Link>
          </div>

          {!analytics?.agent_metrics.length ? (
            <div className="py-8 text-center text-xs text-zinc-500">
              No agent runs recorded yet.
            </div>
          ) : (
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {analytics.agent_metrics.map((m) => (
                <div key={m.agent_name} className="py-2.5 flex items-center justify-between text-xs">
                  <span className="font-medium text-zinc-800 dark:text-zinc-200">
                    {m.agent_name}
                  </span>
                  <div className="flex items-center gap-4 tabular-nums text-zinc-500 dark:text-zinc-400">
                    <span>{m.total_runs} runs</span>
                    <span>{m.avg_latency_ms ?? 0} ms</span>
                    <span className="font-semibold text-zinc-900 dark:text-zinc-100">
                      {m.success_rate}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-100 dark:border-zinc-800">
          <h2 className="text-sm font-semibold text-zinc-950 dark:text-white">Recent Activity</h2>
          <span className="text-xs text-zinc-500">
            API: {health?.status ?? '—'} • DB: {health?.database ?? '—'}
          </span>
        </div>

        {!analytics?.recent_agent_runs.length ? (
          <div className="p-6 text-xs text-zinc-500">No recent agent runs.</div>
        ) : (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {analytics.recent_agent_runs.slice(0, 6).map((run) => (
              <div
                key={run.id}
                className="px-5 py-3 flex items-center justify-between gap-4 text-xs"
              >
                <div className="min-w-0 flex items-center gap-3">
                  <span
                    className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                      run.status === 'success' ? 'bg-emerald-500' : 'bg-amber-500'
                    }`}
                  />
                  <span className="font-medium text-zinc-900 dark:text-zinc-100 shrink-0">
                    {run.agent_name}
                  </span>
                  <span className="text-zinc-500 dark:text-zinc-400 truncate">
                    {run.output_summary}
                  </span>
                </div>
                <span className="shrink-0 tabular-nums text-zinc-400">
                  {run.latency_ms ?? 0} ms
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
