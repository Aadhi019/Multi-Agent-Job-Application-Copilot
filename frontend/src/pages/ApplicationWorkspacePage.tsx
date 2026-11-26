import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import {
  Check,
  Download,
  ExternalLink,
  Mail,
  Play,
  RefreshCw,
  Save,
  X,
} from 'lucide-react'
import { apiClient } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import type {
  DocumentItem,
  FormFillReport,
  InterviewPrepStructured,
  ResumeBulletEvidence,
} from '../types'

type TabKey = 'resume' | 'cover_letter' | 'form_fill' | 'prep' | 'emails' | 'timeline'

const tabs: { key: TabKey; label: string }[] = [
  { key: 'resume', label: 'Tailored Resume' },
  { key: 'cover_letter', label: 'Cover Letter' },
  { key: 'form_fill', label: 'Form Fill' },
  { key: 'prep', label: 'Interview Prep' },
  { key: 'emails', label: 'Emails' },
  { key: 'timeline', label: 'Timeline' },
]

export function ApplicationWorkspacePage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabKey>('resume')
  const [selectedResumeId, setSelectedResumeId] = useState<string | null>(null)
  const [resumeView, setResumeView] = useState<'evidence' | 'diff'>('evidence')
  const [selectedBulletId, setSelectedBulletId] = useState<string | null>(null)
  const [coverDraft, setCoverDraft] = useState('')
  const [tone, setTone] = useState<'formal' | 'friendly' | 'concise'>('formal')
  const [approvalFeedback, setApprovalFeedback] = useState('')
  const [formUrl, setFormUrl] = useState('')
  const [followupType, setFollowupType] = useState<'after_applying' | 'after_interview' | 'thank_you'>(
    'after_applying',
  )
  const [followupTo, setFollowupTo] = useState('')
  const [banner, setBanner] = useState<string | null>(null)

  const { data: detail, isLoading, isError, error } = useQuery({
    queryKey: ['application', id],
    queryFn: () => apiClient.getApplication(id),
    enabled: Boolean(id),
  })

  const { data: allEmails = [] } = useQuery({
    queryKey: ['emails'],
    queryFn: apiClient.listEmails,
  })

  const resumeDocs: DocumentItem[] = (detail?.documents || []).filter((d) => d.type === 'resume')
  const coverDocs: DocumentItem[] = (detail?.documents || []).filter((d) => d.type === 'cover_letter')
  const formFillDocs: DocumentItem[] = (detail?.documents || []).filter((d) => d.type === 'form_fill')
  const emailDraftDocs: DocumentItem[] = (detail?.documents || []).filter((d) => d.type === 'email_draft')
  const prepDocs: DocumentItem[] = (detail?.documents || []).filter((d) => d.type === 'prep')

  const activeResume =
    resumeDocs.find((d) => d.id === selectedResumeId) ||
    resumeDocs.find((d) => d.id === detail?.resume_version_id) ||
    resumeDocs[0]

  const { data: verification } = useQuery({
    queryKey: ['doc-verification', activeResume?.id],
    queryFn: () => apiClient.getDocumentVerification(activeResume!.id),
    enabled: Boolean(activeResume?.id),
  })

  const regenerateBulletMutation = useMutation({
    mutationFn: (bulletId: string) =>
      apiClient.regenerateBullet(activeResume!.id, bulletId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['doc-verification', activeResume?.id] })
      queryClient.invalidateQueries({ queryKey: ['application', id] })
      setBanner('Bullet regenerated and re-verified against profile facts.')
    },
    onError: (err: Error) => setBanner(`Bullet regenerate error: ${err.message}`),
  })
  const activeCover = coverDocs.find((d) => d.id === detail?.cover_letter_id) || coverDocs[0]
  const latestFormFill = formFillDocs[0]?.metadata as unknown as FormFillReport | undefined
  const latestPrep = prepDocs[0]?.metadata?.structured as unknown as InterviewPrepStructured | undefined
  const matchedEmails = allEmails.filter((em) => em.application_id === id)

  useEffect(() => {
    if (detail?.job?.url && !formUrl) {
      setFormUrl(detail.job.url)
    }
  }, [detail?.job?.url])

  useEffect(() => {
    if (activeCover) {
      setCoverDraft(activeCover.content)
      const metaTone = activeCover.metadata?.tone
      if (metaTone === 'formal' || metaTone === 'friendly' || metaTone === 'concise') {
        setTone(metaTone)
      }
    }
  }, [activeCover?.id])

  const approveMutation = useMutation({
    mutationFn: () => apiClient.approveApplication(id, approvalFeedback),
    onSuccess: (updated) => {
      queryClient.setQueryData(['application', id], updated)
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      setBanner('Approved — marked ready_to_submit.')
    },
    onError: (err: Error) => setBanner(`Approval error: ${err.message}`),
  })

  const rejectMutation = useMutation({
    mutationFn: () => apiClient.rejectApplication(id, approvalFeedback),
    onSuccess: (updated) => {
      queryClient.setQueryData(['application', id], updated)
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      setBanner('Rejected — workflow paused.')
    },
    onError: (err: Error) => setBanner(`Rejection error: ${err.message}`),
  })

  const saveCoverMutation = useMutation({
    mutationFn: () => apiClient.updateCoverLetter(id, coverDraft, tone),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['application', id] })
      setBanner('Cover letter edits saved.')
    },
    onError: (err: Error) => setBanner(`Save error: ${err.message}`),
  })

  const regenerateMutation = useMutation({
    mutationFn: (agentName: 'resume_tailor' | 'cover_letter') =>
      apiClient.runAgent(agentName, { application_id: id, tone }),
    onSuccess: (_, agentName) => {
      queryClient.invalidateQueries({ queryKey: ['application', id] })
      setBanner(
        agentName === 'resume_tailor'
          ? 'Generated new tailored resume version.'
          : 'Regenerated cover letter.',
      )
    },
    onError: (err: Error) => setBanner(`Regeneration error: ${err.message}`),
  })

  const formFillMutation = useMutation({
    mutationFn: () => apiClient.runFormFill(id, formUrl),
    onSuccess: (report) => {
      queryClient.invalidateQueries({ queryKey: ['application', id] })
      setBanner(report.notes)
    },
    onError: (err: Error) => setBanner(`Form filler error: ${err.message}`),
  })

  const draftFollowUpMutation = useMutation({
    mutationFn: () => apiClient.draftFollowUp(id, followupType, followupTo),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['application', id] })
      setBanner('Follow-up email drafted (pending approval).')
    },
    onError: (err: Error) => setBanner(`Draft error: ${err.message}`),
  })

  const approveGmailDraftMutation = useMutation({
    mutationFn: (docId: string) => apiClient.approveFollowUpDraft(id, docId),
    onSuccess: (doc) => {
      queryClient.invalidateQueries({ queryKey: ['application', id] })
      const statusText = String(doc.metadata?.status || 'approved')
      setBanner(
        statusText === 'saved_to_gmail'
          ? `Saved to Gmail Drafts (${String(doc.metadata?.gmail_draft_id || '')}).`
          : 'Draft approved locally (connect Gmail in Settings to sync).',
      )
    },
    onError: (err: Error) => setBanner(`Gmail draft error: ${err.message}`),
  })

  const syncEmailsMutation = useMutation({
    mutationFn: () => apiClient.syncEmails(),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['emails'] })
      queryClient.invalidateQueries({ queryKey: ['application', id] })
      setBanner(`Synced ${res.synced_count} email(s); updated ${res.updated_applications} application(s).`)
    },
    onError: (err: Error) => setBanner(`Email sync error: ${err.message}`),
  })

  const prepMutation = useMutation({
    mutationFn: () => apiClient.generateInterviewPrep(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['application', id] })
      setBanner('Interview prep guide generated.')
    },
    onError: (err: Error) => setBanner(`Interview prep error: ${err.message}`),
  })

  const statusMutation = useMutation({
    mutationFn: (nextStatus: string) => apiClient.updateApplicationStatus(id, nextStatus),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['application', id] })
      queryClient.invalidateQueries({ queryKey: ['applications'] })
    },
  })

  if (isLoading) return <div className="text-xs text-zinc-500">Loading workspace...</div>
  if (isError || !detail) {
    return (
      <div className="rounded-lg border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/30 p-4 text-xs text-rose-700">
        {(error as Error)?.message || 'Application not found.'}
      </div>
    )
  }

  const coverage = Number(activeResume?.metadata?.keyword_coverage_score ?? 0)
  const matchedKw = (activeResume?.metadata?.matched_keywords as string[] | undefined) || []
  const missingKw = (activeResume?.metadata?.missing_keywords as string[] | undefined) || []
  const changesMade = (activeResume?.metadata?.changes_made as string[] | undefined) || []

  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4">
        <PageHeader
          title={`${detail.job.title} — ${detail.job.company}`}
          description={`${detail.job.location || 'Unspecified'} • Fit ${
            detail.job.fit_score ?? '—'
          }%`}
          badge={detail.status.replace(/_/g, ' ')}
        />
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={detail.job.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800"
          >
            Posting <ExternalLink className="h-3 w-3" />
          </a>
          <select
            value={detail.status}
            onChange={(e) => statusMutation.mutate(e.target.value)}
            className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs font-medium"
          >
            <option value="draft">draft</option>
            <option value="awaiting_approval">awaiting_approval</option>
            <option value="ready_to_submit">ready_to_submit</option>
            <option value="applied">applied</option>
            <option value="interview">interview</option>
            <option value="offer">offer</option>
            <option value="rejected">rejected</option>
          </select>
        </div>
      </div>

      {banner && (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-4 py-2.5 text-xs text-zinc-700 dark:text-zinc-300">
          {banner}
        </div>
      )}

      {detail.status === 'awaiting_approval' && (
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 border-l-4 border-l-amber-500 bg-white dark:bg-zinc-900 p-5 space-y-3">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-zinc-950 dark:text-white">
                Human review required
              </h2>
              <p className="text-xs text-zinc-500 mt-0.5">
                LangGraph checkpoint paused before any external submission. Review documents below to proceed.
              </p>
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              value={approvalFeedback}
              onChange={(e) => setApprovalFeedback(e.target.value)}
              placeholder="Optional review note..."
              className="flex-1 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-1.5 text-xs"
            />
            <button
              type="button"
              onClick={() => approveMutation.mutate()}
              disabled={approveMutation.isPending}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3.5 py-1.5 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200"
            >
              <Check className="h-3.5 w-3.5" /> Approve
            </button>
            <button
              type="button"
              onClick={() => rejectMutation.mutate()}
              disabled={rejectMutation.isPending}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 px-3.5 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30"
            >
              <X className="h-3.5 w-3.5" /> Reject
            </button>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-zinc-200/90 dark:border-zinc-800/90 bg-white dark:bg-zinc-900 overflow-hidden">
        <div className="flex overflow-x-auto border-b border-zinc-200/80 dark:border-zinc-800/80 px-4">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`whitespace-nowrap px-3.5 py-3 text-xs font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-zinc-900 text-zinc-950 dark:border-white dark:text-white'
                  : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="p-6">
          {activeTab === 'resume' && (
            <div className="space-y-6">
              {/* Verification Summary Card */}
              {verification && (
                <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/70 dark:bg-zinc-800/40 p-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="text-xs font-medium text-zinc-800 dark:text-zinc-200 tabular-nums">
                    Verified{' '}
                    <strong>
                      {verification.verification_report.verified_count +
                        verification.verification_report.rephrased_ok_count}
                      /{verification.verification_report.total_bullets}
                    </strong>{' '}
                    bullets •{' '}
                    <strong>
                      {verification.verification_report.unsupported_removed_count}
                    </strong>{' '}
                    unsupported removed • Keyword coverage{' '}
                    <strong>{coverage.toFixed(1)}%</strong>
                  </div>
                  <div className="inline-flex rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 p-0.5 text-xs">
                    <button
                      type="button"
                      onClick={() => setResumeView('evidence')}
                      className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                        resumeView === 'evidence'
                          ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
                          : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-white'
                      }`}
                    >
                      Evidence
                    </button>
                    <button
                      type="button"
                      onClick={() => setResumeView('diff')}
                      className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                        resumeView === 'diff'
                          ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
                          : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-white'
                      }`}
                    >
                      Diff vs Original
                    </button>
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-medium text-zinc-500">
                    Keyword coverage{' '}
                    <strong className="text-zinc-950 dark:text-white tabular-nums">
                      {coverage.toFixed(1)}%
                    </strong>
                  </span>
                  {resumeDocs.length > 1 && (
                    <select
                      value={activeResume?.id || ''}
                      onChange={(e) => setSelectedResumeId(e.target.value)}
                      className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-2.5 py-1 text-xs"
                    >
                      {resumeDocs.map((d) => (
                        <option key={d.id} value={d.id}>
                          v{d.version}
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => regenerateMutation.mutate('resume_tailor')}
                    disabled={regenerateMutation.isPending}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800"
                  >
                    <RefreshCw className="h-3 w-3" /> Re-tailor
                  </button>
                  <a
                    href={apiClient.getResumeDownloadUrl(detail.id, 'docx')}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3 py-1.5 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800"
                  >
                    <Download className="h-3 w-3" /> DOCX
                  </a>
                  <a
                    href={apiClient.getResumeDownloadUrl(detail.id, 'pdf')}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800"
                  >
                    <Download className="h-3 w-3" /> PDF
                  </a>
                  <a
                    href={apiClient.getResumeDownloadUrl(detail.id, 'md')}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800"
                  >
                    <Download className="h-3 w-3" /> MD
                  </a>
                </div>
              </div>

              {resumeView === 'evidence' && verification && verification.bullets.length > 0 ? (
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
                  <div className="lg:col-span-7 space-y-2.5">
                    {verification.bullets.map((b: ResumeBulletEvidence) => {
                      const isSelected = selectedBulletId === b.id
                      const badgeClass =
                        b.status === 'verified'
                          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                          : b.status === 'rephrased_ok'
                            ? 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200'
                            : 'bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300'
                      const badgeLabel =
                        b.status === 'verified'
                          ? 'Verified'
                          : b.status === 'rephrased_ok'
                            ? 'Rephrased'
                            : 'Removed'
                      return (
                        <div
                          key={b.id}
                          onClick={() => setSelectedBulletId(b.id)}
                          className={`rounded-lg border p-3.5 text-xs cursor-pointer transition-colors ${
                            isSelected
                              ? 'border-zinc-900 dark:border-zinc-200 bg-zinc-50 dark:bg-zinc-800/60'
                              : 'border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50/70 dark:hover:bg-zinc-800/30'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2 mb-1.5">
                            <div className="flex items-center gap-2">
                              <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${badgeClass}`}>
                                {badgeLabel}
                              </span>
                              <span className="text-[11px] text-zinc-400">{b.section}</span>
                            </div>
                            {b.status !== 'unsupported' && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  regenerateBulletMutation.mutate(b.id)
                                }}
                                disabled={regenerateBulletMutation.isPending}
                                className="inline-flex items-center gap-1 text-[11px] font-medium text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
                              >
                                <RefreshCw className="h-3 w-3" /> Regenerate
                              </button>
                            )}
                          </div>
                          <p className="text-zinc-800 dark:text-zinc-200 leading-relaxed">{b.text}</p>
                        </div>
                      )
                    })}
                  </div>

                  {/* Evidence Side Panel */}
                  <div className="lg:col-span-5">
                    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-950 p-4 space-y-3 sticky top-20">
                      <div className="text-xs font-semibold text-zinc-950 dark:text-white">
                        Evidence Inspector
                      </div>
                      {(() => {
                        const activeBullet =
                          verification.bullets.find((b) => b.id === selectedBulletId) ||
                          verification.bullets[0]
                        if (!activeBullet) return null
                        return (
                          <div className="space-y-3 text-xs">
                            <p className="text-zinc-500">{activeBullet.reason}</p>
                            <div className="space-y-2">
                              <div className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                                Source Facts ({activeBullet.evidence_facts.length})
                              </div>
                              {activeBullet.evidence_facts.length === 0 ? (
                                <p className="text-zinc-500">No source facts linked.</p>
                              ) : (
                                activeBullet.evidence_facts.map((fact) => (
                                  <div
                                    key={fact.id}
                                    className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 space-y-1"
                                  >
                                    <div className="flex items-center justify-between text-[11px] text-zinc-400">
                                      <span>{fact.category}</span>
                                      <span className="truncate max-w-[160px]">{fact.source_section}</span>
                                    </div>
                                    <p className="text-zinc-800 dark:text-zinc-200">{fact.text}</p>
                                  </div>
                                ))
                              )}
                            </div>
                          </div>
                        )
                      })()}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div>
                    <h3 className="text-[11px] font-medium uppercase tracking-wider text-zinc-400 mb-2">
                      Master Resume
                    </h3>
                    <pre className="h-96 overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 p-4 font-mono text-xs whitespace-pre-wrap">
                      {detail.master_resume_text || 'No master resume uploaded.'}
                    </pre>
                  </div>
                  <div>
                    <h3 className="text-[11px] font-medium uppercase tracking-wider text-zinc-700 dark:text-zinc-300 mb-2">
                      Tailored Resume (v{activeResume?.version ?? 1})
                    </h3>
                    <pre className="h-96 overflow-auto rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 p-4 font-mono text-xs whitespace-pre-wrap">
                      {activeResume?.content || 'No tailored resume generated.'}
                    </pre>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 text-xs">
                <div className="rounded-lg border border-zinc-200/80 dark:border-zinc-800 p-4 space-y-2">
                  <div className="font-medium text-zinc-900 dark:text-zinc-100">
                    Matched ({matchedKw.length})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {matchedKw.map((kw) => (
                      <span
                        key={kw}
                        className="rounded-md bg-emerald-50 dark:bg-emerald-500/15 px-2 py-0.5 text-emerald-700 dark:text-emerald-300"
                      >
                        {kw}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="rounded-lg border border-zinc-200/80 dark:border-zinc-800 p-4 space-y-2">
                  <div className="font-medium text-zinc-900 dark:text-zinc-100">
                    Missing Requirements — Not Invented ({missingKw.length})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {missingKw.map((kw) => (
                      <span
                        key={kw}
                        className="rounded-md bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 text-zinc-600 dark:text-zinc-300"
                      >
                        {kw}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="rounded-lg border border-zinc-200/80 dark:border-zinc-800 p-4 space-y-2">
                  <div className="font-medium text-zinc-900 dark:text-zinc-100">Changes Made</div>
                  <ul className="list-disc pl-4 space-y-1 text-zinc-600 dark:text-zinc-400">
                    {changesMade.map((c, idx) => (
                      <li key={idx}>{c}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'cover_letter' && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <select
                    value={tone}
                    onChange={(e) => setTone(e.target.value as 'formal' | 'friendly' | 'concise')}
                    className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs"
                  >
                    <option value="formal">Formal</option>
                    <option value="friendly">Friendly</option>
                    <option value="concise">Concise</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => regenerateMutation.mutate('cover_letter')}
                    disabled={regenerateMutation.isPending}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800"
                  >
                    <RefreshCw className="h-3 w-3" /> Regenerate
                  </button>
                </div>

                <button
                  type="button"
                  onClick={() => saveCoverMutation.mutate()}
                  disabled={saveCoverMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3.5 py-1.5 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800"
                >
                  <Save className="h-3 w-3" />
                  {saveCoverMutation.isPending ? 'Saving...' : 'Save Edits'}
                </button>
              </div>

              <textarea
                rows={14}
                value={coverDraft}
                onChange={(e) => setCoverDraft(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent p-4 text-sm leading-relaxed"
              />
            </div>
          )}

          {activeTab === 'form_fill' && (
            <div className="space-y-6">
              <div className="flex flex-col sm:flex-row gap-2.5">
                <input
                  value={formUrl}
                  onChange={(e) => setFormUrl(e.target.value)}
                  placeholder="Application Form URL"
                  className="flex-1 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-2 text-xs"
                />
                <button
                  type="button"
                  onClick={() => formFillMutation.mutate()}
                  disabled={formFillMutation.isPending || !formUrl.trim()}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-zinc-900 dark:bg-zinc-100 px-4 py-2 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 disabled:opacity-60"
                >
                  <Play className="h-3 w-3" />
                  {formFillMutation.isPending ? 'Pre-filling...' : 'Pre-fill (Stop Before Submit)'}
                </button>
              </div>

              {!latestFormFill ? (
                <div className="rounded-lg border border-dashed border-zinc-200 dark:border-zinc-800 p-8 text-center text-xs text-zinc-500">
                  Run Playwright FormFillerAgent to pre-fill fields, attach your tailored PDF, and capture review screenshots.
                </div>
              ) : (
                <div className="space-y-5">
                  <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800/60 p-3.5 text-xs flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <strong>Status:</strong> {latestFormFill.status} •{' '}
                      <strong>Stopped Before Submit:</strong>{' '}
                      {latestFormFill.stopped_before_submit ? 'Yes' : 'No'}
                    </span>
                    <span className="text-zinc-500">{latestFormFill.notes}</span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 space-y-2">
                      <h3 className="font-semibold">
                        Filled / Uploaded ({latestFormFill.filled_fields.length})
                      </h3>
                      {latestFormFill.filled_fields.map((f, idx) => (
                        <div key={idx} className="flex justify-between gap-2 border-b border-zinc-100 dark:border-zinc-800 pb-1">
                          <span className="font-medium">{f.label}</span>
                          <span className="text-zinc-500 truncate max-w-[200px]">{f.value_preview}</span>
                        </div>
                      ))}
                    </div>

                    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 space-y-2">
                      <h3 className="font-semibold">
                        Manual Review ({latestFormFill.unfilled_fields.length})
                      </h3>
                      {latestFormFill.unfilled_fields.length === 0 ? (
                        <p className="text-zinc-500">All detected fields filled.</p>
                      ) : (
                        latestFormFill.unfilled_fields.map((f, idx) => (
                          <div key={idx} className="flex justify-between gap-2 border-b border-zinc-100 dark:border-zinc-800 pb-1">
                            <span>{f.label}</span>
                            <span className="text-zinc-400">{f.field_type}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {latestFormFill.screenshot_urls.length > 0 && (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      {latestFormFill.screenshot_urls.map((src) => (
                        <div key={src} className="rounded-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden">
                          <img
                            src={apiClient.getScreenshotUrl(src)}
                            alt="Application form review screenshot"
                            className="w-full h-auto"
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {activeTab === 'prep' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <p className="text-xs text-zinc-500">
                  Role-specific questions and STAR outlines mapped to your real projects.
                </p>
                <button
                  type="button"
                  onClick={() => prepMutation.mutate()}
                  disabled={prepMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3.5 py-2 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 disabled:opacity-60"
                >
                  <RefreshCw className="h-3 w-3" />
                  {prepMutation.isPending
                    ? 'Generating...'
                    : latestPrep
                      ? 'Regenerate Prep'
                      : 'Generate Prep'}
                </button>
              </div>

              {!latestPrep ? (
                <div className="rounded-lg border border-dashed border-zinc-200 dark:border-zinc-800 p-8 text-center text-xs text-zinc-500">
                  Click Generate Prep to build your tailored interview preparation guide.
                </div>
              ) : (
                <div className="space-y-6 text-xs">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 space-y-2">
                      <h3 className="font-semibold text-sm">Technical Questions</h3>
                      <ul className="list-disc pl-4 space-y-1.5 text-zinc-600 dark:text-zinc-300">
                        {latestPrep.technical_questions.map((q, idx) => (
                          <li key={idx}>{q}</li>
                        ))}
                      </ul>
                    </div>
                    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 space-y-2">
                      <h3 className="font-semibold text-sm">Behavioral Questions</h3>
                      <ul className="list-disc pl-4 space-y-1.5 text-zinc-600 dark:text-zinc-300">
                        {latestPrep.behavioral_questions.map((q, idx) => (
                          <li key={idx}>{q}</li>
                        ))}
                      </ul>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {latestPrep.star_outlines.map((s, idx) => (
                      <div
                        key={idx}
                        className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 space-y-2 bg-zinc-50/70 dark:bg-zinc-800/40"
                      >
                        <div className="font-semibold text-zinc-950 dark:text-white">{s.question}</div>
                        {s.mapped_project_or_role && (
                          <div className="text-[11px] text-zinc-500">
                            Source: {s.mapped_project_or_role}
                          </div>
                        )}
                        <p><strong>Situation:</strong> {s.situation}</p>
                        <p><strong>Task:</strong> {s.task}</p>
                        <p><strong>Action:</strong> {s.action}</p>
                        <p><strong>Result:</strong> {s.result}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'emails' && (
            <div className="space-y-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={followupType}
                    onChange={(e) =>
                      setFollowupType(e.target.value as 'after_applying' | 'after_interview' | 'thank_you')
                    }
                    className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs"
                  >
                    <option value="after_applying">After Applying</option>
                    <option value="after_interview">After Interview</option>
                    <option value="thank_you">Thank You</option>
                  </select>
                  <input
                    value={followupTo}
                    onChange={(e) => setFollowupTo(e.target.value)}
                    placeholder="Recruiter email (optional)"
                    className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-1.5 text-xs"
                  />
                  <button
                    type="button"
                    onClick={() => draftFollowUpMutation.mutate()}
                    disabled={draftFollowUpMutation.isPending}
                    className="rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3 py-1.5 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800"
                  >
                    {draftFollowUpMutation.isPending ? 'Drafting...' : 'Draft Follow-Up'}
                  </button>
                </div>

                <button
                  type="button"
                  onClick={() => syncEmailsMutation.mutate()}
                  disabled={syncEmailsMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800"
                >
                  <Mail className="h-3 w-3" />
                  {syncEmailsMutation.isPending ? 'Syncing...' : 'Sync Gmail'}
                </button>
              </div>

              <div className="space-y-3">
                <h3 className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                  Follow-Up Drafts
                </h3>
                {emailDraftDocs.length === 0 ? (
                  <p className="text-xs text-zinc-500">No follow-up drafts yet.</p>
                ) : (
                  emailDraftDocs.map((doc) => {
                    const statusText = String(doc.metadata?.status || 'pending_approval')
                    return (
                      <div key={doc.id} className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 space-y-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="text-xs font-semibold">
                            {String(doc.metadata?.subject || 'Follow-Up')} (v{doc.version})
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="rounded-md bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 text-[11px]">
                              {statusText}
                            </span>
                            {statusText === 'pending_approval' && (
                              <button
                                type="button"
                                onClick={() => approveGmailDraftMutation.mutate(doc.id)}
                                disabled={approveGmailDraftMutation.isPending}
                                className="rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3 py-1 text-xs font-medium text-white dark:text-zinc-950"
                              >
                                Save Gmail Draft
                              </button>
                            )}
                          </div>
                        </div>
                        <pre className="text-xs whitespace-pre-wrap text-zinc-600 dark:text-zinc-300 font-sans">
                          {doc.content}
                        </pre>
                      </div>
                    )
                  })
                )}
              </div>

              <div className="space-y-3">
                <h3 className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                  Matched Gmail Replies ({matchedEmails.length})
                </h3>
                {matchedEmails.length === 0 ? (
                  <p className="text-xs text-zinc-500">No matched emails synced yet.</p>
                ) : (
                  matchedEmails.map((em) => (
                    <div key={em.id} className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-3 text-xs space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold">{em.subject}</span>
                        <span className="rounded-md bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 text-[11px]">
                          {em.classification}
                        </span>
                      </div>
                      <p className="text-zinc-500">{em.snippet}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {activeTab === 'timeline' && (
            <div className="space-y-3 text-xs">
              <div>
                <span className="font-semibold">Status:</span> {detail.status}
              </div>
              <div>
                <span className="font-semibold">Updated:</span>{' '}
                {new Date(detail.updated_at).toLocaleString()}
              </div>
              {detail.notes && (
                <div className="rounded-lg bg-zinc-50 dark:bg-zinc-800/70 p-3 whitespace-pre-wrap">
                  {detail.notes}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
