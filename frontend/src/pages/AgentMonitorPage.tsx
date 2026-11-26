import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import type { WsRunEvent } from '../types'

export function AgentMonitorPage() {
  const queryClient = useQueryClient()
  const [liveEvents, setLiveEvents] = useState<WsRunEvent[]>([])
  const [wsConnected, setWsConnected] = useState(false)
  const [agentFilter, setAgentFilter] = useState('')

  const { data: analytics } = useQuery({
    queryKey: ['analytics-summary'],
    queryFn: apiClient.getAnalyticsSummary,
    refetchInterval: 10000,
  })

  const { data: runs = [], isLoading } = useQuery({
    queryKey: ['agent-runs'],
    queryFn: () => apiClient.listAgentRuns(100),
    refetchInterval: 10000,
  })

  useEffect(() => {
    const ws = new WebSocket(apiClient.getWsUrl('global'))
    ws.onopen = () => setWsConnected(true)
    ws.onclose = () => setWsConnected(false)
    ws.onerror = () => setWsConnected(false)
    ws.onmessage = (evt) => {
      try {
        const parsed = JSON.parse(evt.data) as WsRunEvent
        if (parsed.agent_name) {
          setLiveEvents((prev) => [parsed, ...prev].slice(0, 30))
          queryClient.invalidateQueries({ queryKey: ['agent-runs'] })
          queryClient.invalidateQueries({ queryKey: ['analytics-summary'] })
        }
      } catch {
        // ignore non-event payloads
      }
    }
    return () => ws.close()
  }, [queryClient])

  const filteredRuns = agentFilter ? runs.filter((r) => r.agent_name === agentFilter) : runs

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <PageHeader
          title="Agent Monitor"
          description="Live WebSocket stream, per-agent success rates, latency, and token consumption."
        />
        <div className="inline-flex items-center gap-2 rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs font-medium">
          <span className={`h-1.5 w-1.5 rounded-full ${wsConnected ? 'bg-emerald-500' : 'bg-zinc-400'}`} />
          <span>{wsConnected ? 'WebSocket Live' : 'Polling'}</span>
        </div>
      </div>

      {Boolean(analytics?.agent_metrics.length) && (
        <section className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 overflow-hidden">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-zinc-200/80 dark:divide-zinc-800/80">
            {(analytics?.agent_metrics || []).map((m) => (
              <div key={m.agent_name} className="p-4 space-y-1">
                <div className="text-xs font-medium text-zinc-500">{m.agent_name}</div>
                <div className="text-xl font-semibold tabular-nums">{m.success_rate}%</div>
                <div className="text-[11px] text-zinc-500 tabular-nums">
                  {m.total_runs} runs • {m.avg_latency_ms ?? 0} ms • {m.total_tokens} tok
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 p-5 space-y-3">
        <h2 className="text-xs font-medium uppercase tracking-wider text-zinc-400">
          Live Stream (/ws/runs/global)
        </h2>
        {liveEvents.length === 0 ? (
          <p className="text-xs text-zinc-500">Waiting for agent events...</p>
        ) : (
          <div className="max-h-44 overflow-auto space-y-1.5 font-mono text-xs">
            {liveEvents.map((ev, idx) => (
              <div
                key={`${ev.timestamp}-${idx}`}
                className="flex items-center justify-between gap-3 rounded-md bg-zinc-50 dark:bg-zinc-800/60 px-3 py-1.5"
              >
                <div className="truncate">
                  <span className="font-semibold">{ev.agent_name}</span>{' '}
                  <span className="text-zinc-400">[{ev.step}]</span> {ev.message}
                </div>
                <span className="shrink-0 text-zinc-400">
                  {new Date(ev.timestamp).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-zinc-200/80 dark:border-zinc-800/80">
          <h2 className="text-sm font-semibold">Run History ({filteredRuns.length})</h2>
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-2.5 py-1 text-xs"
          >
            <option value="">All agents</option>
            {Array.from(new Set(runs.map((r) => r.agent_name))).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>

        {isLoading ? (
          <div className="p-6 text-xs text-zinc-500">Loading runs...</div>
        ) : filteredRuns.length === 0 ? (
          <div className="p-6 text-xs text-zinc-500">No agent runs recorded yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-800/60 text-zinc-500 border-b border-zinc-200/70 dark:border-zinc-800">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Agent</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Input</th>
                  <th className="px-4 py-2.5 font-medium">Output</th>
                  <th className="px-4 py-2.5 font-medium text-right">Latency</th>
                  <th className="px-4 py-2.5 font-medium text-right">Tokens</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {filteredRuns.map((run) => (
                  <tr key={run.id} className="hover:bg-zinc-50/70 dark:hover:bg-zinc-800/30">
                    <td className="px-4 py-2.5 font-medium whitespace-nowrap">{run.agent_name}</td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className={`h-1.5 w-1.5 rounded-full ${
                            run.status === 'success' ? 'bg-emerald-500' : 'bg-rose-500'
                          }`}
                        />
                        {run.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 max-w-xs truncate text-zinc-500">{run.input_summary}</td>
                    <td className="px-4 py-2.5 max-w-xs truncate">{run.output_summary}</td>
                    <td className="px-4 py-2.5 whitespace-nowrap text-right tabular-nums text-zinc-500">
                      {run.latency_ms ?? '—'} ms
                    </td>
                    <td className="px-4 py-2.5 whitespace-nowrap text-right tabular-nums text-zinc-500">
                      {run.tokens_used ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
