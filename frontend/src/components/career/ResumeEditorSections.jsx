import React from 'react'
import { SECTION_IDS, WORK_AUTH_PLACEHOLDER } from './resumeEditorModel.js'

const labelStyle = { display: 'block', fontSize: '12.5px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '6px' }
const inputStyle = { width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '13px' }
const cardStyle = { border: '1px solid var(--border)', borderRadius: '10px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px' }
const btnStyle = { background: 'var(--bg-card)', border: '1px solid var(--border)', padding: '6px 12px', borderRadius: '8px', fontSize: '12.5px', fontWeight: 600, color: 'var(--text-primary)', cursor: 'pointer' }
const errStyle = { color: '#b91c1c', fontSize: '11.5px', marginTop: '4px' }

function Field({ id, label, value, onChange, error, type = 'text', placeholder, multiline, rows = 3 }) {
  const Tag = multiline ? 'textarea' : 'input'
  return (
    <div>
      <label htmlFor={id} style={labelStyle}>{label}</label>
      <Tag
        id={id}
        type={multiline ? undefined : type}
        rows={multiline ? rows : undefined}
        value={value}
        placeholder={placeholder}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(e) => onChange(e.target.value)}
        style={inputStyle}
      />
      {error && <div id={`${id}-error`} role="alert" style={errStyle}>{error}</div>}
    </div>
  )
}

function Section({ section, title, hint, onAdd, addLabel, children, sectionRef, highlighted }) {
  return (
    <fieldset
      id={SECTION_IDS[section]}
      tabIndex={-1}
      ref={sectionRef}
      style={{ border: highlighted ? '2px solid var(--brand, #3b82f6)' : '1px solid var(--border)', borderRadius: '12px', padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px', margin: 0 }}
    >
      <legend style={{ fontSize: '14px', fontWeight: 800, color: 'var(--text-primary)', padding: '0 6px' }}>{title}</legend>
      {hint && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{hint}</div>}
      {children}
      {onAdd && <div><button type="button" onClick={onAdd} style={btnStyle}>{addLabel}</button></div>}
    </fieldset>
  )
}

/** Education, projects, experience, and links/details sections of the My resume editor. */
export default function ResumeEditorSections({ sections, errors, dispatch, onLinkChange, refs, focusSection }) {
  const err = (name, i, f) => errors?.[name]?.[i]?.[f]
  const row = (name, i, children, label) => (
    <div key={`${name}-${i}`} style={cardStyle}>
      {children}
      <div><button type="button" onClick={() => dispatch({ type: 'remove', section: name, index: i })} style={btnStyle} aria-label={`Remove ${label} ${i + 1}`}>Remove</button></div>
    </div>
  )
  const up = (name, i, field) => (value) => dispatch({ type: 'update', section: name, index: i, field, value })
  const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px' }
  const links = sections.links || {}
  const lerr = errors?.links || {}

  return (
    <>
      <Section section="education" title="Education" onAdd={() => dispatch({ type: 'add', section: 'education' })} addLabel="+ Add education" sectionRef={refs?.education} highlighted={focusSection === 'education'}>
        {sections.education.length === 0 && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>No education added yet.</div>}
        {sections.education.map((e, i) => row('education', i, (
          <div style={grid}>
            <Field id={`edu-institution-${i}`} label="Institution" value={e.institution} onChange={up('education', i, 'institution')} error={err('education', i, 'institution')} />
            <Field id={`edu-degree-${i}`} label="Degree" value={e.degree} onChange={up('education', i, 'degree')} error={err('education', i, 'degree')} />
            <Field id={`edu-field-${i}`} label="Field of study" value={e.field_of_study} onChange={up('education', i, 'field_of_study')} />
            <Field id={`edu-start-${i}`} label="Start year" value={e.start_year} onChange={up('education', i, 'start_year')} error={err('education', i, 'start_year')} placeholder="2021" />
            <Field id={`edu-end-${i}`} label="End year" value={e.end_year} onChange={up('education', i, 'end_year')} error={err('education', i, 'end_year')} placeholder="2025" />
            <Field id={`edu-grade-${i}`} label="CGPA / grade" value={e.cgpa_or_grade} onChange={up('education', i, 'cgpa_or_grade')} error={err('education', i, 'cgpa_or_grade')} placeholder="8.5 or 3.6/4.0" />
          </div>
        ), 'education'))}
      </Section>

      <Section section="projects" title="Projects" onAdd={() => dispatch({ type: 'add', section: 'projects' })} addLabel="+ Add project" sectionRef={refs?.projects} highlighted={focusSection === 'projects'}>
        {sections.projects.length === 0 && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>No projects added yet.</div>}
        {sections.projects.map((p, i) => row('projects', i, (
          <>
            <div style={grid}>
              <Field id={`proj-title-${i}`} label="Title" value={p.title} onChange={up('projects', i, 'title')} error={err('projects', i, 'title')} />
              <Field id={`proj-tech-${i}`} label="Technologies (comma-separated)" value={p.technologies} onChange={up('projects', i, 'technologies')} />
              <Field id={`proj-link-${i}`} label="Link" value={p.link} onChange={up('projects', i, 'link')} error={err('projects', i, 'link')} placeholder="https://" />
            </div>
            <Field id={`proj-desc-${i}`} label="Description" value={p.description} onChange={up('projects', i, 'description')} multiline />
          </>
        ), 'project'))}
      </Section>

      <Section section="experience" title="Experience (optional)" onAdd={() => dispatch({ type: 'add', section: 'experience' })} addLabel="+ Add experience" sectionRef={refs?.experience} highlighted={focusSection === 'experience'}>
        {sections.experience.map((x, i) => row('experience', i, (
          <>
            <div style={grid}>
              <Field id={`exp-company-${i}`} label="Company" value={x.company} onChange={up('experience', i, 'company')} error={err('experience', i, 'company')} />
              <Field id={`exp-role-${i}`} label="Role" value={x.role_title} onChange={up('experience', i, 'role_title')} error={err('experience', i, 'role_title')} />
              <Field id={`exp-start-${i}`} label="Start" value={x.start_date} onChange={up('experience', i, 'start_date')} placeholder="Jun 2024" />
              {!x.is_current && <Field id={`exp-end-${i}`} label="End" value={x.end_date} onChange={up('experience', i, 'end_date')} placeholder="Aug 2024" />}
            </div>
            <label htmlFor={`exp-current-${i}`} style={{ fontSize: '12.5px', display: 'flex', gap: '6px', alignItems: 'center' }}>
              <input id={`exp-current-${i}`} type="checkbox" checked={x.is_current} onChange={(e) => up('experience', i, 'is_current')(e.target.checked)} />
              I currently work here
            </label>
            <Field id={`exp-high-${i}`} label="Highlights (one per line)" value={x.highlights} onChange={up('experience', i, 'highlights')} multiline />
          </>
        ), 'experience'))}
      </Section>

      <Section section="links" title="Links and details" hint="Used to fill your application pack." sectionRef={refs?.links} highlighted={focusSection === 'links'}>
        <div style={grid}>
          <Field id="resume-linkedin" label="LinkedIn URL" value={links.linkedin_url || ''} onChange={onLinkChange('linkedin_url')} error={lerr.linkedin_url} placeholder="https://www.linkedin.com/in/..." />
          <Field id="resume-github" label="GitHub URL" value={links.github_url || ''} onChange={onLinkChange('github_url')} error={lerr.github_url} placeholder="https://github.com/..." />
          <Field id="resume-portfolio" label="Portfolio URL" value={links.portfolio_url || ''} onChange={onLinkChange('portfolio_url')} error={lerr.portfolio_url} placeholder="https://" />
          <Field id="resume-work-auth" label="Work authorization" value={links.work_authorization || ''} onChange={onLinkChange('work_authorization')} placeholder={WORK_AUTH_PLACEHOLDER} />
          <Field id="resume-notice" label="Notice period" value={links.notice_period || ''} onChange={onLinkChange('notice_period')} placeholder="e.g. Immediately available" />
        </div>
      </Section>
    </>
  )
}
