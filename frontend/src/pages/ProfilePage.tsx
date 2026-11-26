import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileUp, Plus, Save, Trash2, CheckCircle2, AlertCircle, X } from 'lucide-react'
import { apiClient } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import type { EducationItem, ExperienceItem, Preferences, Profile, ProjectItem } from '../types'

const emptyPreferences: Preferences = {
  target_roles: [],
  preferred_locations: [],
  remote_preference: 'any',
  cover_letter_tone: 'formal',
  job_sources: ['remotive', 'manual'],
  phone: '',
  linkedin_url: '',
  github_url: '',
  portfolio_url: '',
}

export function ProfilePage() {
  const queryClient = useQueryClient()
  const { data: profile, isLoading, isError, error } = useQuery({
    queryKey: ['profile'],
    queryFn: apiClient.getProfile,
  })

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [skills, setSkills] = useState<string[]>([])
  const [skillInput, setSkillInput] = useState('')
  const [experience, setExperience] = useState<ExperienceItem[]>([])
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [education, setEducation] = useState<EducationItem[]>([])
  const [preferences, setPreferences] = useState<Preferences>(emptyPreferences)
  const [masterResumeText, setMasterResumeText] = useState('')
  const [autoPopulate, setAutoPopulate] = useState(true)
  const [newFactText, setNewFactText] = useState('')
  const [newFactCategory, setNewFactCategory] = useState('experience_bullet')
  const [banner, setBanner] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const { data: facts = [] } = useQuery({
    queryKey: ['profile-facts'],
    queryFn: apiClient.listProfileFacts,
  })

  const rebuildFactsMutation = useMutation({
    mutationFn: apiClient.rebuildProfileFacts,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile-facts'] })
      setBanner({ type: 'success', text: 'Evidence facts rebuilt from profile.' })
    },
  })

  const addFactMutation = useMutation({
    mutationFn: () =>
      apiClient.createProfileFact({
        category: newFactCategory,
        text: newFactText,
        source_section: 'Manual Entry',
      }),
    onSuccess: () => {
      setNewFactText('')
      queryClient.invalidateQueries({ queryKey: ['profile-facts'] })
    },
  })

  const deleteFactMutation = useMutation({
    mutationFn: apiClient.deleteProfileFact,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['profile-facts'] }),
  })

  const syncFromProfile = (p: Profile) => {
    setName(p.name)
    setEmail(p.email)
    setSkills(p.skills)
    setExperience(p.experience)
    setProjects(p.projects)
    setEducation(p.education)
    setPreferences({ ...emptyPreferences, ...p.preferences })
    setMasterResumeText(p.master_resume_text)
  }

  useEffect(() => {
    if (profile) {
      syncFromProfile(profile)
    }
  }, [profile])

  const saveMutation = useMutation({
    mutationFn: apiClient.updateProfile,
    onSuccess: (updated) => {
      queryClient.setQueryData(['profile'], updated)
      queryClient.invalidateQueries({ queryKey: ['profile-facts'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      syncFromProfile(updated)
      setBanner({ type: 'success', text: 'Profile saved and saved job match scores updated.' })
    },
    onError: (err: Error) => {
      setBanner({ type: 'error', text: err.message })
    },
  })

  const uploadMutation = useMutation({
    mutationFn: ({ file, populate }: { file: File; populate: boolean }) =>
      apiClient.uploadResume(file, populate),
    onSuccess: (res) => {
      queryClient.setQueryData(['profile'], res.profile)
      queryClient.invalidateQueries({ queryKey: ['profile-facts'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      syncFromProfile(res.profile)
      setBanner({
        type: 'success',
        text: `Uploaded ${res.filename} (${res.extracted_chars} chars extracted via ${res.parser_mode}) and updated job match scores.`,
      })
    },
    onError: (err: Error) => {
      setBanner({ type: 'error', text: err.message })
    },
  })

  const handleSave = () => {
    setBanner(null)
    saveMutation.mutate({
      name,
      email,
      skills,
      experience,
      projects,
      education,
      preferences,
      master_resume_text: masterResumeText,
    })
  }

  const handleAddSkill = () => {
    const trimmed = skillInput.trim()
    if (!trimmed) return
    if (!skills.includes(trimmed)) {
      setSkills([...skills, trimmed])
    }
    setSkillInput('')
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setBanner(null)
    uploadMutation.mutate({ file, populate: autoPopulate })
    e.target.value = ''
  }

  if (isLoading) {
    return <div className="text-sm text-slate-500">Loading profile...</div>
  }

  if (isError) {
    return (
      <div className="rounded-xl border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/40 p-5 text-sm text-rose-700 dark:text-rose-300">
        Failed to load profile: {(error as Error).message}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <PageHeader
          title="Profile & Master Resume"
          description="Source of truth for resume tailoring. Agents only reorder or rephrase facts stored here."
        />
        <button
          type="button"
          onClick={handleSave}
          disabled={saveMutation.isPending}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-zinc-900 dark:bg-zinc-100 px-4 py-2 text-xs font-medium text-white dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-60"
        >
          <Save className="h-3.5 w-3.5" />
          <span>{saveMutation.isPending ? 'Saving...' : 'Save Profile'}</span>
        </button>
      </div>

      {banner && (
        <div
          className={`flex items-center gap-2.5 rounded-xl border p-4 text-sm ${
            banner.type === 'success'
              ? 'border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-200'
              : 'border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/40 text-rose-800 dark:text-rose-200'
          }`}
        >
          {banner.type === 'success' ? (
            <CheckCircle2 className="h-4 w-4 shrink-0" />
          ) : (
            <AlertCircle className="h-4 w-4 shrink-0" />
          )}
          <span>{banner.text}</span>
        </div>
      )}

      {/* Resume Upload Card */}
      <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold">Upload Master Resume</h3>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Supports PDF, DOCX, TXT, and Markdown. Extracts text and optionally parses structured sections.
            </p>
          </div>
          <label className="inline-flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
            <input
              type="checkbox"
              checked={autoPopulate}
              onChange={(e) => setAutoPopulate(e.target.checked)}
              className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
            />
            Auto-populate skills & history
          </label>
        </div>

        <label className="mt-4 flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 dark:border-slate-700 p-6 cursor-pointer hover:border-brand-500 transition-colors">
          <FileUp className="h-7 w-7 text-brand-600 dark:text-indigo-400 mb-2" />
          <span className="text-sm font-medium">
            {uploadMutation.isPending ? 'Extracting and parsing resume...' : 'Click to upload resume file'}
          </span>
          <span className="text-xs text-slate-500 mt-1">.pdf, .docx, .txt, .md</span>
          <input
            type="file"
            accept=".pdf,.docx,.txt,.md"
            onChange={handleFileChange}
            disabled={uploadMutation.isPending}
            className="hidden"
          />
        </label>
      </section>

      {/* Contact & Links */}
      <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
        <h3 className="text-base font-semibold">Identity & Application Links</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">Full Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">Email</label>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">Phone</label>
            <input
              value={preferences.phone}
              onChange={(e) => setPreferences({ ...preferences, phone: e.target.value })}
              placeholder="+1 (555) 000-0000"
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">LinkedIn URL</label>
            <input
              value={preferences.linkedin_url}
              onChange={(e) => setPreferences({ ...preferences, linkedin_url: e.target.value })}
              placeholder="https://linkedin.com/in/..."
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">GitHub URL</label>
            <input
              value={preferences.github_url}
              onChange={(e) => setPreferences({ ...preferences, github_url: e.target.value })}
              placeholder="https://github.com/..."
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">Portfolio URL</label>
            <input
              value={preferences.portfolio_url}
              onChange={(e) => setPreferences({ ...preferences, portfolio_url: e.target.value })}
              placeholder="https://..."
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
            />
          </div>
        </div>
      </section>

      {/* Skills */}
      <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
        <h3 className="text-base font-semibold">Verified Skills</h3>
        <div className="flex gap-2">
          <input
            value={skillInput}
            onChange={(e) => setSkillInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                handleAddSkill()
              }
            }}
            placeholder="Add a skill (e.g., Python, FastAPI, PostgreSQL)"
            className="flex-1 rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={handleAddSkill}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 dark:border-slate-700 px-3 py-2 text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <Plus className="h-4 w-4" /> Add
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {skills.length === 0 ? (
            <span className="text-xs text-slate-500">No skills added yet.</span>
          ) : (
            skills.map((skill) => (
              <span
                key={skill}
                className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 dark:bg-brand-500/20 px-3 py-1 text-xs font-medium text-brand-700 dark:text-indigo-200"
              >
                {skill}
                <button
                  type="button"
                  onClick={() => setSkills(skills.filter((s) => s !== skill))}
                  className="hover:text-rose-600 transition-colors"
                  aria-label={`Remove ${skill}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            ))
          )}
        </div>
      </section>

      {/* Experience */}
      <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold">Work Experience</h3>
          <button
            type="button"
            onClick={() =>
              setExperience([
                ...experience,
                { company: '', title: '', start_date: '', end_date: '', location: '', highlights: [] },
              ])
            }
            className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 dark:text-indigo-400 hover:underline"
          >
            <Plus className="h-3.5 w-3.5" /> Add Role
          </button>
        </div>
        {experience.length === 0 && (
          <p className="text-xs text-slate-500">No work experience entries yet.</p>
        )}
        <div className="space-y-4">
          {experience.map((item, idx) => (
            <div
              key={idx}
              className="rounded-lg border border-slate-200 dark:border-slate-800 p-4 space-y-3"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-500">Role #{idx + 1}</span>
                <button
                  type="button"
                  onClick={() => setExperience(experience.filter((_, i) => i !== idx))}
                  className="text-rose-500 hover:text-rose-600"
                  aria-label="Remove experience"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <input
                  value={item.title}
                  onChange={(e) => {
                    const copy = [...experience]
                    copy[idx] = { ...item, title: e.target.value }
                    setExperience(copy)
                  }}
                  placeholder="Job Title"
                  className="rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-1.5 text-sm"
                />
                <input
                  value={item.company}
                  onChange={(e) => {
                    const copy = [...experience]
                    copy[idx] = { ...item, company: e.target.value }
                    setExperience(copy)
                  }}
                  placeholder="Company"
                  className="rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-1.5 text-sm"
                />
                <input
                  value={item.start_date}
                  onChange={(e) => {
                    const copy = [...experience]
                    copy[idx] = { ...item, start_date: e.target.value }
                    setExperience(copy)
                  }}
                  placeholder="Start (e.g. 2023-01)"
                  className="rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-1.5 text-sm"
                />
                <input
                  value={item.end_date}
                  onChange={(e) => {
                    const copy = [...experience]
                    copy[idx] = { ...item, end_date: e.target.value }
                    setExperience(copy)
                  }}
                  placeholder="End (e.g. Present)"
                  className="rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-1.5 text-sm"
                />
              </div>
              <textarea
                rows={3}
                value={item.highlights.join('\n')}
                onChange={(e) => {
                  const copy = [...experience]
                  copy[idx] = {
                    ...item,
                    highlights: e.target.value.split('\n').filter((line) => line.trim() !== ''),
                  }
                  setExperience(copy)
                }}
                placeholder="Bullet points (one per line)"
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-2 text-sm"
              />
            </div>
          ))}
        </div>
      </section>

      {/* Projects & Education */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold">Projects</h3>
            <button
              type="button"
              onClick={() =>
                setProjects([
                  ...projects,
                  { name: '', description: '', tech_stack: [], url: '', highlights: [] },
                ])
              }
              className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 dark:text-indigo-400 hover:underline"
            >
              <Plus className="h-3.5 w-3.5" /> Add Project
            </button>
          </div>
          {projects.length === 0 && <p className="text-xs text-slate-500">No projects added yet.</p>}
          {projects.map((proj, idx) => (
            <div key={idx} className="rounded-lg border border-slate-200 dark:border-slate-800 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <input
                  value={proj.name}
                  onChange={(e) => {
                    const copy = [...projects]
                    copy[idx] = { ...proj, name: e.target.value }
                    setProjects(copy)
                  }}
                  placeholder="Project Name"
                  className="flex-1 rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-1.5 text-sm"
                />
                <button
                  type="button"
                  onClick={() => setProjects(projects.filter((_, i) => i !== idx))}
                  className="text-rose-500"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <textarea
                rows={2}
                value={proj.description}
                onChange={(e) => {
                  const copy = [...projects]
                  copy[idx] = { ...proj, description: e.target.value }
                  setProjects(copy)
                }}
                placeholder="Summary & impact"
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-1.5 text-sm"
              />
            </div>
          ))}
        </section>

        <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold">Education</h3>
            <button
              type="button"
              onClick={() =>
                setEducation([
                  ...education,
                  { institution: '', degree: '', graduation_year: '', gpa: '' },
                ])
              }
              className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 dark:text-indigo-400 hover:underline"
            >
              <Plus className="h-3.5 w-3.5" /> Add Education
            </button>
          </div>
          {education.length === 0 && (
            <p className="text-xs text-slate-500">No education entries added yet.</p>
          )}
          {education.map((edu, idx) => (
            <div key={idx} className="rounded-lg border border-slate-200 dark:border-slate-800 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <input
                  value={edu.institution}
                  onChange={(e) => {
                    const copy = [...education]
                    copy[idx] = { ...edu, institution: e.target.value }
                    setEducation(copy)
                  }}
                  placeholder="University / Institution"
                  className="flex-1 rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-1.5 text-sm"
                />
                <button
                  type="button"
                  onClick={() => setEducation(education.filter((_, i) => i !== idx))}
                  className="text-rose-500"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <input
                  value={edu.degree}
                  onChange={(e) => {
                    const copy = [...education]
                    copy[idx] = { ...edu, degree: e.target.value }
                    setEducation(copy)
                  }}
                  placeholder="Degree"
                  className="rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-1.5 text-sm"
                />
                <input
                  value={edu.graduation_year}
                  onChange={(e) => {
                    const copy = [...education]
                    copy[idx] = { ...edu, graduation_year: e.target.value }
                    setEducation(copy)
                  }}
                  placeholder="Graduation Year"
                  className="rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent px-3 py-1.5 text-sm"
                />
              </div>
            </div>
          ))}
        </section>
      </div>

      {/* Master Resume Raw Text */}
      <section className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-3">
        <h3 className="text-base font-semibold">Master Resume Text</h3>
        <textarea
          rows={10}
          value={masterResumeText}
          onChange={(e) => setMasterResumeText(e.target.value)}
          placeholder="Paste or upload your complete master resume here..."
          className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-transparent p-3 font-mono text-xs"
        />
      </section>

      {/* Extracted Evidence Facts */}
      <section className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-base font-semibold">Verified Evidence Facts ({facts.length})</h3>
            <p className="text-xs text-zinc-500">
              Atomic facts extracted from your profile. ResumeTailorAgent cites only these facts.
            </p>
          </div>
          <button
            type="button"
            onClick={() => rebuildFactsMutation.mutate()}
            disabled={rebuildFactsMutation.isPending}
            className="rounded-lg border border-zinc-200 dark:border-zinc-700 px-3 py-1.5 text-xs font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800"
          >
            {rebuildFactsMutation.isPending ? 'Rebuilding...' : 'Rebuild Facts'}
          </button>
        </div>

        <div className="flex flex-col sm:flex-row gap-2">
          <select
            value={newFactCategory}
            onChange={(e) => setNewFactCategory(e.target.value)}
            className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs"
          >
            <option value="experience_bullet">experience_bullet</option>
            <option value="project_detail">project_detail</option>
            <option value="skill">skill</option>
            <option value="education">education</option>
            <option value="certification">certification</option>
          </select>
          <input
            value={newFactText}
            onChange={(e) => setNewFactText(e.target.value)}
            placeholder="Add a verified fact..."
            className="flex-1 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent px-3 py-1.5 text-xs"
          />
          <button
            type="button"
            onClick={() => addFactMutation.mutate()}
            disabled={!newFactText.trim() || addFactMutation.isPending}
            className="rounded-lg bg-zinc-900 dark:bg-zinc-100 px-3.5 py-1.5 text-xs font-medium text-white dark:text-zinc-950 disabled:opacity-50"
          >
            Add Fact
          </button>
        </div>

        {facts.length === 0 ? (
          <p className="text-xs text-zinc-500">No facts extracted yet. Save your profile or upload a resume.</p>
        ) : (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800 max-h-80 overflow-y-auto">
            {facts.map((fact) => (
              <div key={fact.id} className="py-2.5 flex items-start justify-between gap-3 text-xs">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium">
                      {fact.category}
                    </span>
                    <span className="text-[11px] text-zinc-400">{fact.source_section}</span>
                  </div>
                  <p className="text-zinc-800 dark:text-zinc-200">{fact.text}</p>
                </div>
                <button
                  type="button"
                  onClick={() => deleteFactMutation.mutate(fact.id)}
                  className="text-zinc-400 hover:text-rose-600"
                  aria-label="Delete fact"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
