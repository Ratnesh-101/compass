// Bundled by chatTaskIntake.test.mjs so the real component can be rendered under node:test.
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import IntakePreviewCard from '../../src/components/chat/IntakePreviewCard.jsx'

export function renderCard(pendingAction) {
  return renderToStaticMarkup(
    <IntakePreviewCard pendingAction={pendingAction} onConfirm={() => {}} onCancel={() => {}} />
  )
}
