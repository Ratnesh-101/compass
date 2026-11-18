/**
 * Dynamic contextual follow-up suggestion generator for Assistant Chat.
 *
 * Rules:
 * 1. Empty chat (new conversation): show NO chips at all.
 * 2. After completed assistant reply: generate 2 to 3 contextual follow-up chips.
 * 3. Never repeat suggestions already asked by the user in this conversation.
 * 4. Suppress chips on error, refusal, or "I don't know" responses.
 * 5. Uses API suggestions if present, otherwise builds from real data:
 *    conversation topic domain, real tasks & deadlines, and latest reply content.
 * 6. Keep chips short (<= 60 chars where possible, ellipsis truncated if longer).
 */

/**
 * Checks if the assistant message is an error, refusal, or unhelpful generic response.
 */
export function isRefusalOrError(text, isError = false) {
  if (isError) return true
  if (!text || typeof text !== 'string') return true
  const trimmed = text.trim()
  if (trimmed.length < 5) return true

  const lower = trimmed.toLowerCase()
  const refusalPatterns = [
    "i don't know",
    "i do not know",
    "i'm not sure",
    "i am not sure",
    "cannot answer",
    "unable to answer",
    "i cannot assist",
    "i am unable to",
    "as an ai",
    "i don't have access to",
    "i do not have access to",
    "i apologize, but i cannot",
    "i'm sorry, but i cannot",
    "something went wrong",
    "error occurred",
    "failed to generate",
    "connection error",
    "rate limit",
  ]

  return refusalPatterns.some((pat) => lower.includes(pat))
}

/**
 * Normalizes a string for deduplication comparison.
 */
function normalizeForComparison(str) {
  return (str || '')
    .toLowerCase()
    .replace(/[^\w\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Checks whether a candidate suggestion was already asked by the user.
 */
function wasAlreadyAsked(candidate, pastUserQueries) {
  const normCandidate = normalizeForComparison(candidate)
  if (!normCandidate) return true

  for (const query of pastUserQueries) {
    const normQuery = normalizeForComparison(query)
    if (!normQuery) continue
    if (normCandidate === normQuery) return true
    if (normQuery.length >= 12 && normCandidate.includes(normQuery)) return true
    if (normCandidate.length >= 12 && normQuery.includes(normCandidate)) return true
  }
  return false
}

/**
 * Truncates suggestion text to max 60 chars cleanly.
 */
export function formatSuggestionText(text, maxLen = 60) {
  if (!text || text.length <= maxLen) return text
  return text.slice(0, maxLen - 1).trim() + '…'
}

/**
 * Generates 2 to 3 contextual follow-up suggestions.
 *
 * @param {Object} params
 * @param {Object} params.latestMessage - The latest completed assistant message
 * @param {Array} params.messages - Entire conversation message history
 * @param {Array} params.tasks - Real user tasks from workspace state
 * @returns {Array<string>} Array of 2 to 3 suggestion strings
 */
export function generateFollowUpSuggestions({
  latestMessage,
  messages = [],
  tasks = [],
}) {
  if (!latestMessage || latestMessage.role !== 'assistant') return []
  if (latestMessage.error || isRefusalOrError(latestMessage.text, latestMessage.error)) return []

  // 1. Gather all past user queries to prevent repeating anything already asked
  const pastUserQueries = messages
    .filter((m) => m.role === 'user' && m.text)
    .map((m) => m.text)

  // Empty chat (new conversation): show NO chips at all before the user has asked something
  if (pastUserQueries.length === 0) {
    return []
  }

  // 2. If API response already includes suggestions, validate and use them
  if (Array.isArray(latestMessage.suggestions) && latestMessage.suggestions.length > 0) {
    return latestMessage.suggestions.slice(0, 3)
  }
  if (Array.isArray(latestMessage.follow_ups) && latestMessage.follow_ups.length > 0) {
    return latestMessage.follow_ups.slice(0, 3)
  }

  // Find the user query that immediately preceded this assistant message
  const assistantIndex = messages.lastIndexOf(latestMessage)
  let lastUserText = ''
  if (assistantIndex > 0) {
    for (let i = assistantIndex - 1; i >= 0; i--) {
      if (messages[i].role === 'user' && messages[i].text) {
        lastUserText = messages[i].text
        break
      }
    }
  }

  const replyText = (latestMessage.text || '').toLowerCase()
  const combinedContext = `${lastUserText} ${latestMessage.text || ''}`.toLowerCase()

  // Real tasks partitioned by domain
  const safeTasks = Array.isArray(tasks) ? tasks : []
  const hackathonTasks = safeTasks.filter((t) => t.domain === 'hackathon')
  const courseworkTasks = safeTasks.filter((t) => t.domain === 'coursework')
  const codeTasks = safeTasks.filter((t) => t.domain === 'code')
  const hasDeadlines = safeTasks.some((t) => t.countdown || t.due_date || t.deadline)

  // Domain & topic detection
  const isHackathon =
    combinedContext.includes('hackathon') ||
    combinedContext.includes('devpost') ||
    combinedContext.includes('nebius') ||
    combinedContext.includes('bounty') ||
    combinedContext.includes('prize') ||
    combinedContext.includes('token factory')

  const isCareer =
    combinedContext.includes('internship') ||
    combinedContext.includes('career') ||
    combinedContext.includes('job') ||
    combinedContext.includes('application') ||
    combinedContext.includes('resume') ||
    combinedContext.includes('eligible') ||
    combinedContext.includes('radar') ||
    combinedContext.includes('hiring')

  // Word-boundary matching: "exam" must not fire on "example", "lab" not on "available", "class" not on "classify"
  const isCoursework = /\b(coursework|cs 61\w*|risc-v|synthesis|labs?|exams?|homework|assignments?|class(?:es)?|lectures?|syllabus)\b/.test(combinedContext)
  // A real coursework signal in the conversation (used before offering any lab-specific chip)
  const hasCourseworkWord = /\b(coursework|homework|assignments?|exams?|lectures?|syllabus|classes|class|course|cs 61\w*)\b/.test(combinedContext)

  // Code domain requires genuine architectural, algorithmic or code context (not a casual 'database' or 'api' word in prose)
  const isCode =
    combinedContext.includes('matryoshka') ||
    combinedContext.includes('embedding') ||
    combinedContext.includes('pgvector') ||
    combinedContext.includes('hnsw') ||
    combinedContext.includes('refactor') ||
    combinedContext.includes('benchmark') ||
    combinedContext.includes('tradeoff') ||
    combinedContext.includes('algorithm') ||
    combinedContext.includes('vector search') ||
    (codeTasks.length > 0 && (combinedContext.includes('code') || combinedContext.includes('function') || combinedContext.includes('sql') || combinedContext.includes('python')))

  const isScheduleOrPlanning =
    combinedContext.includes('schedule') ||
    combinedContext.includes('calendar') ||
    combinedContext.includes('conflict') ||
    combinedContext.includes('weekend') ||
    /(plan|agenda|todo|tasks?|schedule)[\s\S]*today|today[\s\S]*(plan|agenda|todo|tasks?|schedule)/.test(combinedContext) ||
    combinedContext.includes('roadmap') ||
    combinedContext.includes('overdue') ||
    combinedContext.includes('deadline') ||
    /due/.test(combinedContext) ||
    combinedContext.includes('prioritize')

  // Score domains so the most pertinent domain gets primary placement
  const domainsByPriority = []
  if (isCareer) domainsByPriority.push('career')
  if (isCoursework) domainsByPriority.push('coursework')
  if (isHackathon) domainsByPriority.push('hackathon')
  if (isCode) domainsByPriority.push('code')
  if (isScheduleOrPlanning) domainsByPriority.push('schedule')

  const candidatePool = []

  for (const domain of domainsByPriority) {
    if (domain === 'career') {
      if (combinedContext.includes('eligib') || combinedContext.includes('requirement')) {
        candidatePool.push('What are the eligibility requirements?')
      }
      candidatePool.push('Find matching internships')
      candidatePool.push('Review my upcoming deadlines')
    } else if (domain === 'coursework') {
      candidatePool.push('Review upcoming coursework deadlines')
      candidatePool.push('Check for schedule conflicts this week')
      if (courseworkTasks.length > 0) {
        candidatePool.push('Prioritize my coursework tasks')
      } else if (/\blabs?\b/.test(replyText) && hasCourseworkWord) {
        candidatePool.push('Summarize key lab takeaways')
      }
    } else if (domain === 'hackathon') {
      candidatePool.push('Plan the work before the deadline')
      candidatePool.push('Check for schedule conflicts this week')
      if (combinedContext.includes('devpost') || combinedContext.includes('deadline') || combinedContext.includes('verify')) {
        candidatePool.push('Verify deadline on Devpost')
      } else if (hackathonTasks.length > 0) {
        candidatePool.push('Review open hackathon tasks')
      } else {
        candidatePool.push('What are the hackathon deliverables?')
      }
    } else if (domain === 'code') {
      // Only suggest technical tradeoffs/approaches if the reply actually discusses them
      if (replyText.includes('approach') || replyText.includes('we chose') || replyText.includes('configured') || replyText.includes('matryoshka') || replyText.includes('pgvector') || replyText.includes('algorithm')) {
        candidatePool.push('Why did we choose this approach?')
      }
      if (replyText.includes('tradeoff') || replyText.includes('vs ') || replyText.includes('versus') || replyText.includes('pgvector') || replyText.includes('embedding') || replyText.includes('matryoshka') || replyText.includes('architecture')) {
        candidatePool.push('What are the tradeoffs?')
      }
      if (codeTasks.length > 0) {
        candidatePool.push('Check for code debt in tasks')
      }
      if (replyText.includes('perform') || replyText.includes('optim') || replyText.includes('benchmark') || replyText.includes('latency') || replyText.includes('fast similarity')) {
        candidatePool.push('How can we optimize performance?')
      }
    } else if (domain === 'schedule') {
      if (!candidatePool.includes('Check for schedule conflicts this week')) {
        candidatePool.push('Check for schedule conflicts this week')
      }
      candidatePool.push('Plan an optimal roadmap for today')
      if (hasDeadlines) {
        candidatePool.push('Show overdue tasks')
      }
    }
  }

  // When unsure show none: do not show ungrounded generic chips
  if (candidatePool.length === 0) {
    return []
  }

  // Filter out any candidates that the user has already asked in this conversation
  const eligibleSuggestions = []
  for (const candidate of candidatePool) {
    if (!wasAlreadyAsked(candidate, pastUserQueries)) {
      if (!eligibleSuggestions.includes(candidate)) {
        eligibleSuggestions.push(candidate)
      }
    }
    if (eligibleSuggestions.length >= 3) break
  }

  // Return 2 to 3 suggestions (or whatever genuine non-repeated items remain, max 3)
  return eligibleSuggestions.slice(0, 3)
}
