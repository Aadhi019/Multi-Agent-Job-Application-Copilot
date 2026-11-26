export interface HealthStatus {
  status: 'ok' | 'degraded'
  service: string
  environment: string
  database: 'connected' | 'disconnected'
  database_error: string | null
  timestamp: string
}

export type ApplicationStatus =
  | 'draft'
  | 'tailoring'
  | 'awaiting_approval'
  | 'ready_to_submit'
  | 'applied'
  | 'interview'
  | 'rejected'
  | 'offer'

export interface ExperienceItem {
  company: string
  title: string
  start_date: string
  end_date: string
  location: string
  highlights: string[]
}

export interface ProjectItem {
  name: string
  description: string
  tech_stack: string[]
  url: string
  highlights: string[]
}

export interface EducationItem {
  institution: string
  degree: string
  graduation_year: string
  gpa: string
}

export interface Preferences {
  target_roles: string[]
  preferred_locations: string[]
  remote_preference: 'remote' | 'hybrid' | 'onsite' | 'any'
  cover_letter_tone: 'formal' | 'friendly' | 'concise'
  job_sources: string[]
  phone: string
  linkedin_url: string
  github_url: string
  portfolio_url: string
}

export interface Profile {
  user_id: string
  name: string
  email: string
  skills: string[]
  experience: ExperienceItem[]
  projects: ProjectItem[]
  education: EducationItem[]
  preferences: Preferences
  master_resume_text: string
}

export type ProfileUpdatePayload = Partial<Omit<Profile, 'user_id'>>

export interface ResumeUploadResponse {
  filename: string
  extracted_chars: number
  parser_mode: 'groq' | 'heuristic' | 'text_only'
  parsed_fields: {
    name?: string | null
    email?: string | null
    skills: string[]
    experience: ExperienceItem[]
    projects: ProjectItem[]
    education: EducationItem[]
  }
  profile: Profile
}

export interface AuthStatus {
  gmail_connected: boolean
  gmail_email: string | null
  google_oauth_configured: boolean
  groq_configured: boolean
  groq_model: string
  scopes: string[]
}

export interface GoogleAuthStart {
  auth_url: string
  state: string
}

export interface GroqTestResult {
  ok: boolean
  model: string
  latency_ms: number | null
  message: string
}

export interface Job {
  id: string
  source: string
  title: string
  company: string
  location: string
  url: string
  description: string
  fit_score: number | null
  fit_reason: string | null
  discovered_at: string
}

export interface JobDiscoveryPayload {
  query?: string
  target_roles?: string[]
  skills?: string[]
  location?: string
  remote_preference?: string
  sources?: string[]
  limit?: number
}

export interface JobDiscoveryResult {
  discovered_count: number
  deduplicated_count: number
  jobs: Job[]
  agent_run_id: string | null
}

export interface JobImportPayload {
  url: string
  title?: string
  company?: string
  location?: string
  description?: string
}

export interface DocumentItem {
  id: string
  application_id: string | null
  type: 'resume' | 'cover_letter' | 'prep' | 'email_draft' | 'form_fill'
  content: string
  metadata: Record<string, unknown>
  version: number
  created_at: string
}

export interface FormFieldReportItem {
  field_name: string
  label: string
  field_type: string
  status: 'filled' | 'unfilled' | 'uploaded' | 'skipped'
  value_preview: string
}

export interface FormFillReport {
  url: string
  status: 'ready_for_review' | 'blocked' | 'failed'
  filled_fields: FormFieldReportItem[]
  unfilled_fields: FormFieldReportItem[]
  generated_answers: { question: string; answer: string }[]
  screenshot_paths: string[]
  screenshot_urls: string[]
  blocked_reason: string | null
  stopped_before_submit: boolean
  notes: string
}

export interface EmailRecord {
  id: string
  gmail_message_id: string
  application_id: string | null
  classification: string
  subject: string
  snippet: string
  received_at: string
}

export interface TrackerSyncResult {
  synced_count: number
  updated_applications: number
  emails: EmailRecord[]
}

export interface StarOutline {
  question: string
  mapped_project_or_role: string
  situation: string
  task: string
  action: string
  result: string
}

export interface InterviewPrepStructured {
  technical_questions: string[]
  behavioral_questions: string[]
  star_outlines: StarOutline[]
  company_research_notes: string[]
  questions_to_ask: string[]
}

export interface AgentMetricSummary {
  agent_name: string
  total_runs: number
  success_count: number
  failed_count: number
  success_rate: number
  avg_latency_ms: number | null
  total_tokens: number
}

export interface AnalyticsSummary {
  total_jobs: number
  total_applications: number
  counts_by_status: Record<string, number>
  response_rate: number
  avg_time_per_application_seconds: number | null
  agent_metrics: AgentMetricSummary[]
  recent_agent_runs: AgentRunItem[]
}

export interface WsRunEvent {
  run_id: string
  agent_name: string
  step: string
  status: string
  message: string
  timestamp: string
}

export interface ProfileFact {
  id: string
  user_id: string
  category: string
  text: string
  source_section: string
  embedding_id: string | null
  created_at: string
}

export interface VerificationReport {
  total_bullets: number
  verified_count: number
  rephrased_ok_count: number
  unsupported_removed_count: number
  hallucination_rate: number
  keyword_coverage_score: number
  missing_requirements: string[]
  unsupported_removed: { text: string; reason: string }[]
  loops_used: number
}

export interface ResumeBulletEvidence {
  id: string
  document_id: string
  section: string
  text: string
  fact_ids: string[]
  status: 'verified' | 'rephrased_ok' | 'unsupported' | string
  jd_keywords: string[]
  reason: string
  evidence_facts: ProfileFact[]
}

export interface DocumentVerification {
  document_id: string
  verification_report: VerificationReport
  bullets: ResumeBulletEvidence[]
}

export interface ApplicationSummary {
  id: string
  job_id: string
  status: ApplicationStatus | string
  job_title: string
  company: string
  location: string
  fit_score: number | null
  job_url: string
  applied_at: string | null
  updated_at: string
  notes: string
}

export interface ApplicationDetail {
  id: string
  job_id: string
  status: ApplicationStatus | string
  resume_version_id: string | null
  cover_letter_id: string | null
  applied_at: string | null
  updated_at: string
  notes: string
  job: Job
  master_resume_text: string
  documents: DocumentItem[]
}

export interface AgentRunItem {
  id: string
  agent_name: string
  input_summary: string
  output_summary: string
  status: string
  latency_ms: number | null
  tokens_used: number | null
  error: string | null
  created_at: string
}
