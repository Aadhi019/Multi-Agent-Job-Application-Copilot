import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  Briefcase,
  FileCheck2,
  LayoutDashboard,
  Menu,
  Moon,
  Settings,
  Sun,
  UserCircle2,
  X,
} from 'lucide-react'
import { apiClient } from '../api/client'
import { useTheme } from '../hooks/useTheme'

const workspaceNav = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/jobs', label: 'Jobs', icon: Briefcase },
  { to: '/applications', label: 'Applications', icon: FileCheck2 },
  { to: '/profile', label: 'Profile', icon: UserCircle2 },
]

const systemNav = [
  { to: '/agents', label: 'Agent Monitor', icon: Activity },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function routeLabel(pathname: string): string {
  if (pathname === '/') return 'Overview'
  if (pathname.startsWith('/jobs')) return 'Jobs'
  if (pathname.startsWith('/applications/')) return 'Application Workspace'
  if (pathname.startsWith('/applications')) return 'Applications'
  if (pathname.startsWith('/profile')) return 'Profile'
  if (pathname.startsWith('/agents')) return 'Agent Monitor'
  if (pathname.startsWith('/settings')) return 'Settings'
  return 'Workspace'
}

export function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const { theme, toggleTheme } = useTheme()
  const { pathname } = useLocation()

  const { data: health, isError } = useQuery({
    queryKey: ['health'],
    queryFn: apiClient.getHealth,
    refetchInterval: 30000,
    retry: 1,
  })

  const healthLabel = isError
    ? 'Offline'
    : health?.status === 'ok'
      ? 'Connected'
      : 'Degraded'

  const healthDotClass = isError
    ? 'bg-rose-500'
    : health?.status === 'ok'
      ? 'bg-emerald-500'
      : 'bg-amber-500'

  const renderNavLink = (item: { to: string; label: string; icon: typeof LayoutDashboard; end?: boolean }) => {
    const Icon = item.icon
    return (
      <NavLink
        key={item.to}
        to={item.to}
        end={item.end}
        onClick={() => setMobileOpen(false)}
        className={({ isActive }) =>
          `group flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
            isActive
              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
              : 'text-zinc-600 hover:bg-zinc-200/60 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-zinc-800/70 dark:hover:text-zinc-100'
          }`
        }
      >
        <Icon className="h-4 w-4 shrink-0 opacity-80 group-hover:opacity-100" />
        <span>{item.label}</span>
      </NavLink>
    )
  }

  return (
    <div className="min-h-screen flex bg-[#fafafa] dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100">
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-zinc-950/40 backdrop-blur-[2px] lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 w-60 flex flex-col transform bg-[#f4f4f5] dark:bg-zinc-900/95 border-r border-zinc-200/80 dark:border-zinc-800/80 transition-transform duration-200 lg:static lg:translate-x-0 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex h-14 items-center justify-between px-4 border-b border-zinc-200/80 dark:border-zinc-800/80">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-950 text-xs font-bold tracking-tight">
              JC
            </div>
            <span className="text-[13px] font-semibold tracking-tight text-zinc-950 dark:text-white">
              Job Copilot
            </span>
          </div>
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            className="lg:hidden p-1 rounded-md text-zinc-500 hover:bg-zinc-200/70 dark:hover:bg-zinc-800"
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 p-3 space-y-6 overflow-y-auto" aria-label="Main navigation">
          <div>
            <div className="px-3 mb-1.5 text-[11px] font-medium uppercase tracking-[0.06em] text-zinc-400 dark:text-zinc-500">
              Workspace
            </div>
            <div className="space-y-0.5">{workspaceNav.map(renderNavLink)}</div>
          </div>

          <div>
            <div className="px-3 mb-1.5 text-[11px] font-medium uppercase tracking-[0.06em] text-zinc-400 dark:text-zinc-500">
              System
            </div>
            <div className="space-y-0.5">{systemNav.map(renderNavLink)}</div>
          </div>
        </nav>

        <div className="p-3 border-t border-zinc-200/80 dark:border-zinc-800/80">
          <div className="flex items-center justify-between px-2 py-1.5 text-[11px] text-zinc-500 dark:text-zinc-400">
            <span>Review-gated mode</span>
            <span className="inline-flex items-center gap-1.5 font-medium text-zinc-700 dark:text-zinc-300">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Active
            </span>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 flex items-center justify-between px-4 sm:px-8 bg-[#fafafa]/90 dark:bg-zinc-950/90 backdrop-blur border-b border-zinc-200/80 dark:border-zinc-800/80 sticky top-0 z-20">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="lg:hidden p-1.5 rounded-md text-zinc-600 hover:bg-zinc-200/60 dark:text-zinc-300 dark:hover:bg-zinc-800"
              aria-label="Open navigation"
            >
              <Menu className="h-4 w-4" />
            </button>
            <div className="flex items-center gap-2 text-[13px]">
              <span className="text-zinc-400 dark:text-zinc-500">Copilot</span>
              <span className="text-zinc-300 dark:text-zinc-700">/</span>
              <span className="font-medium text-zinc-900 dark:text-zinc-100">
                {routeLabel(pathname)}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-2.5 py-1 text-xs font-medium text-zinc-700 dark:text-zinc-300">
              <span className={`h-1.5 w-1.5 rounded-full ${healthDotClass}`} />
              <span>{healthLabel}</span>
            </div>

            <button
              type="button"
              onClick={toggleTheme}
              className="p-1.5 rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              aria-label="Toggle color theme"
            >
              {theme === 'dark' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
          </div>
        </header>

        <main className="flex-1 px-4 sm:px-8 py-7 max-w-6xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
