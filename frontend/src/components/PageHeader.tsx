interface PageHeaderProps {
  title: string
  description: string
  badge?: string
}

export function PageHeader({ title, description, badge }: PageHeaderProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
      <div>
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-xl sm:text-2xl font-semibold tracking-[-0.02em] text-zinc-950 dark:text-white">
            {title}
          </h1>
          {badge && (
            <span className="rounded-md border border-zinc-200 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 text-[11px] font-medium text-zinc-700 dark:text-zinc-300 capitalize">
              {badge}
            </span>
          )}
        </div>
        <p className="mt-1 text-[13px] text-zinc-500 dark:text-zinc-400">{description}</p>
      </div>
    </div>
  )
}
