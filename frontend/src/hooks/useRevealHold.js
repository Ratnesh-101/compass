import { useEffect, useRef, useState } from 'react'

// After the answer has fully arrived, keep the streaming bubble until the eased-in text catches up (bounded).
export const REVEAL_HOLD_MAX_MS = 2000

/**
 * Holds the swap from the streaming bubble to the finished message.
 * hold(requestId, finish) defers `finish`; flush() runs it once (reveal caught up or timeout);
 * cancel() drops it (new chat, other conversation). A finish for a request that is no longer active is dropped.
 */
export default function useRevealHold(activeRequestIdRef) {
  const [streamDone, setStreamDone] = useState(false)
  const pendingFinalRef = useRef(null)
  const holdTimerRef = useRef(null)

  const clearTimer = () => {
    if (holdTimerRef.current) {
      clearTimeout(holdTimerRef.current)
      holdTimerRef.current = null
    }
  }

  const cancelRevealHold = () => {
    clearTimer()
    pendingFinalRef.current = null
    setStreamDone(false)
  }

  const flushPendingFinal = () => {
    clearTimer()
    const pending = pendingFinalRef.current
    pendingFinalRef.current = null
    setStreamDone(false)
    if (pending && pending.requestId === activeRequestIdRef.current) pending.finish()
  }

  const holdFinal = (requestId, finish) => {
    pendingFinalRef.current = { requestId, finish }
    setStreamDone(true)
    holdTimerRef.current = setTimeout(flushPendingFinal, REVEAL_HOLD_MAX_MS)
  }

  useEffect(() => () => {
    clearTimer()
    pendingFinalRef.current = null
  }, [])

  return { streamDone, holdFinal, flushPendingFinal, cancelRevealHold }
}
