import { createContext } from 'react'

// Which My resume section to scroll to and focus: { section: 'education' | 'projects' | 'experience' | 'links' | null, nonce }.
// Set by CareerCopilot when '+ Add to profile' or 'add your education' opens My resume.
export const ResumeFocusContext = createContext({ section: null, nonce: 0 })
