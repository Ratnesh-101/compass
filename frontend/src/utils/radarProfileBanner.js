// Decides whether the Radar "complete your profile" banner shows, and what it says.
// academic_year can never be derived from a resume (set in Candidate Profile);
// grad_year is filled automatically by importing a resume.

const ACADEMIC_YEAR_TITLE = 'Add your year of study to confirm eligibility'
const GRAD_YEAR_TITLE = 'Add your graduation year to confirm eligibility'
const ACADEMIC_YEAR_BODY =
  "Resume import can't tell which year you are in. Set it in your Candidate Profile so Compass can check year-restricted internships."
const GRAD_YEAR_BODY =
  'Your graduation year is missing. Import a resume in Resume Studio or add it in your Candidate Profile.'

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
