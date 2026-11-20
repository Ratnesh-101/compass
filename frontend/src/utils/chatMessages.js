// Pure helpers that turn a finished stream into chat messages.

// "Continue response": extend the same assistant bubble instead of adding a new one.
export function mergeContinuation(prev, continueMessageId, addedText, doneData) {
  return prev.map(m => {
    if (m.id === continueMessageId || (!m.id && m.role === 'assistant' && m === prev[prev.length - 1])) {
      const combined = (m.text && addedText.startsWith(m.text))
        ? addedText
        : (m.text ? `${m.text}\n${addedText}` : addedText)
      return {
        ...m,
        text: combined,
        isTruncated: Boolean(doneData?.is_truncated),
        is_truncated: Boolean(doneData?.is_truncated),
        evidence: doneData?.evidence || m.evidence,
        tasks: Array.isArray(doneData?.tasks) ? doneData.tasks : m.tasks,
      }
    }
    return m
  })
}

export function buildAssistantMessage(finalText, receivedThought, doneData) {
  return {
    role: 'assistant',
    text: finalText,
    thought: receivedThought || null,
    tasks: Array.isArray(doneData?.tasks) ? doneData.tasks : null,
    evidence: doneData?.evidence || null,
    isTruncated: Boolean(doneData?.is_truncated),
    is_truncated: Boolean(doneData?.is_truncated),
    verifiable: doneData?.verifiable,
    pending_action: doneData?.pending_action || doneData?.data?.pending_action,
    can_undo: Boolean(doneData?.can_undo || doneData?.data?.can_undo),
    data: doneData?.data || {
      pending_action: doneData?.pending_action,
      can_undo: doneData?.can_undo,
    },
  }
}
