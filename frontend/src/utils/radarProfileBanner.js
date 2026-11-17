// Decides whether the Radar "complete your profile" banner shows, and what it says.
// Importing a resume now fills the year of study (stated "3rd year", or worked out from the degree
// dates) and the graduation year, so this banner only appears for what the resume really did not say.

const ACADEMIC_YEAR_TITLE = 'Add your year of study to confirm eligibility'
const GRAD_YEAR_TITLE = 'Add your graduation year to confirm eligibility'
const ACADEMIC_YEAR_BODY =
  'We could not find your year of study. Add it in your Candidate Profile so Compass can check year-restricted internships.'
const GRAD_YEAR_BODY =
  'We could not find your graduation year. Upload your resume, or add it in your Candidate Profile.'

export function getProfileBannerInfo(profile) {
  const missing = Array.isArray(profile?.missing_fields_limiting_eligibility)
    ? profile.missing_fields_limiting_eligibility
    : []
  const missingAcademicYear = missing.includes('academic_year')
  const missingGradYear = missing.includes('grad_year')
  const show = missingAcademicYear || missingGradYear

  const bodies = []
  if (missingAcademicYear) bodies.push(ACADEMIC_YEAR_BODY)
  if (missingGradYear) bodies.push(GRAD_YEAR_BODY)

  return {
    show,
    missingAcademicYear,
    missingGradYear,
    title: missingAcademicYear ? ACADEMIC_YEAR_TITLE : missingGradYear ? GRAD_YEAR_TITLE : '',
    body: bodies.join(' '),
  }
}
