import './skeleton.css'

export function SkeletonBlock({ width = '100%', height = 14, radius, className = '', style }) {
  return (
    <span
      className={`sk-block ${className}`.trim()}
      aria-hidden="true"
      style={{ width, height, borderRadius: radius, ...style }}
    />
  )
}

export function SkeletonText({ lines = 3, lastWidth = '60%' }) {
  return (
    <div className="sk-stack" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <SkeletonBlock key={i} height={12} width={i === lines - 1 ? lastWidth : '100%'} />
      ))}
    </div>
  )
}

export function SkeletonRegion({ label = 'Loading', className = '', style, children }) {
  return (
    <div
      className={`sk-region ${className}`.trim()}
      role="status"
      aria-busy="true"
      aria-live="polite"
      style={style}
    >
      <span className="sr-only">{label}</span>
      <div aria-hidden="true">{children}</div>
    </div>
  )
}

function TaskRowsBody({ rows }) {
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="sk-card sk-row">
          <SkeletonBlock width={10} height={10} radius="50%" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <SkeletonText lines={2} />
          </div>
          <SkeletonBlock width={64} height={22} />
        </div>
      ))}
    </>
  )
}

function RadarCardsBody({ count }) {
  return (
    <div className="sk-grid">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="sk-card">
          <SkeletonBlock width="70%" height={16} />
          <div style={{ height: 10 }} />
          <SkeletonBlock width="45%" height={12} />
          <div className="sk-chips">
            {Array.from({ length: 3 }, (_, j) => (
              <SkeletonBlock key={j} width={64} height={22} radius={11} />
            ))}
          </div>
          <SkeletonBlock width="100%" height={36} />
        </div>
      ))}
    </div>
  )
}

function ChatRowsBody({ rows }) {
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="sk-row">
          <SkeletonBlock width={16} height={16} />
          <SkeletonText lines={2} />
        </div>
      ))}
    </>
  )
}

function StatGridBody() {
  return (
    <div className="sk-grid sk-grid-4">
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="sk-card">
          <SkeletonBlock width="50%" height={12} />
          <div style={{ height: 10 }} />
          <SkeletonBlock width="35%" height={24} />
        </div>
      ))}
    </div>
  )
}

function ChipsBody({ count, width = 84 }) {
  return (
    <div className="sk-chips">
      {Array.from({ length: count }, (_, i) => (
        <SkeletonBlock key={i} width={width} height={32} radius={16} />
      ))}
    </div>
  )
}

export function TaskListSkeleton({ rows = 5 }) {
  return (
    <SkeletonRegion label="Loading tasks">
      <TaskRowsBody rows={rows} />
    </SkeletonRegion>
  )
}

export function DashboardSkeleton() {
  return (
    <SkeletonRegion label="Loading your dashboard">
      <StatGridBody />
      <ChipsBody count={5} />
      <div className="sk-cols">
        <div>
          <TaskRowsBody rows={5} />
        </div>
        <div className="sk-card">
          <SkeletonText lines={4} />
        </div>
      </div>
    </SkeletonRegion>
  )
}

export function TimelineSkeleton() {
  return (
    <SkeletonRegion label="Loading your timeline">
      <ChipsBody count={4} />
      <TaskRowsBody rows={6} />
    </SkeletonRegion>
  )
}

export function RadarCardsSkeleton({ count = 4 }) {
  return (
    <SkeletonRegion label="Loading opportunities">
      <RadarCardsBody count={count} />
    </SkeletonRegion>
  )
}

export function ChatHistorySkeleton({ rows = 6 }) {
  return (
    <SkeletonRegion label="Loading chat history">
      <ChatRowsBody rows={rows} />
    </SkeletonRegion>
  )
}

const LABELS = {
  career: 'Career Copilot',
  dashboard: 'dashboard',
  timeline: 'timeline',
  chat: 'chat',
}

function TabVariantBody({ variant }) {
  if (variant === 'dashboard') {
    return (
      <>
        <StatGridBody />
        <TaskRowsBody rows={5} />
      </>
    )
  }
  if (variant === 'timeline') {
    return (
      <>
        <ChipsBody count={4} />
        <TaskRowsBody rows={6} />
      </>
    )
  }
  if (variant === 'chat') {
    return (
      <div className="sk-cols">
        <div>
          <ChatRowsBody rows={6} />
        </div>
        <div className="sk-card" style={{ height: 320 }} />
      </div>
    )
  }
  return (
    <>
      <ChipsBody count={4} width={96} />
      <RadarCardsBody count={4} />
    </>
  )
}

export function TabSkeleton({ variant = 'career' }) {
  return (
    <SkeletonRegion label={`Loading ${LABELS[variant] || 'page'}`} className="sk-tab">
      <SkeletonBlock width="40%" height={26} />
      <div style={{ height: 10 }} />
      <SkeletonBlock width="60%" height={14} />
      <TabVariantBody variant={variant} />
    </SkeletonRegion>
  )
}
