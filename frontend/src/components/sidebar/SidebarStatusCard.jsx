import React from 'react'

export default function SidebarStatusCard({
  collapsed,
  isOnline,
  totalActive,
  backendStatus,
  onRetryConnection,
  onOpenTelemetry,
  children
}) {
  const canClick = (!isOnline && Boolean(onRetryConnection)) || Boolean(onOpenTelemetry)

  const handleAction = () => {
    if (!isOnline && onRetryConnection) {
      onRetryConnection()
    } else if (onOpenTelemetry) {
      onOpenTelemetry()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleAction()
    }
  }

  const titleText = isOnline
    ? `${totalActive} tasks synced: ${backendStatus} (Click for telemetry)`
    : `Reconnecting: ${backendStatus} (Click to wake up)`

  const ariaLabelText = isOnline
    ? `${totalActive} tasks synced: ${backendStatus}`
    : `Reconnecting: ${backendStatus}`

  const styles = (
    <style>{`
      .sbs-card {
        transition: all 0.15s ease;
      }
      .sbs-card:focus-visible {
        outline: 2px solid var(--accent, #f5a623);
        outline-offset: 2px;
      }
      .sbs-card-expanded:hover {
        background: var(--sidebar-hover, rgba(255, 255, 255, 0.04)) !important;
        border-color: rgba(255, 255, 255, 0.16) !important;
      }
      .sbs-badge {
        background: rgba(245, 166, 35, 0.14);
        background: color-mix(in srgb, var(--accent, #f5a623) 14%, transparent);
        border: 1px solid rgba(245, 166, 35, 0.28);
        border: 1px solid color-mix(in srgb, var(--accent, #f5a623) 28%, transparent);
      }
      .sbs-badge-collapsed:hover {
        background: rgba(245, 166, 35, 0.22) !important;
        background: color-mix(in srgb, var(--accent, #f5a623) 22%, transparent) !important;
        border-color: rgba(245, 166, 35, 0.42) !important;
        border-color: color-mix(in srgb, var(--accent, #f5a623) 42%, transparent) !important;
      }
      .sbs-ring-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        position: absolute;
        box-shadow: 0 0 0 1.5px var(--sidebar-bg, #18181b);
        flex-shrink: 0;
      }
      .sbs-ring-dot-online {
        background: #1c8a62;
      }
      .sbs-ring-dot-reconnecting {
        background: #f5a623;
      }
      .sbs-bolt-flicker {
        transform-origin: center;
      }
      @media (prefers-reduced-motion: no-preference) {
        .sbs-badge-online {
          animation: sbs-breathe 3.2s ease-in-out infinite;
        }
        .sbs-badge-reconnecting {
          animation: sbs-pulse-amber 1.2s ease-in-out infinite;
        }
        .sbs-bolt-flicker {
          animation: sbs-flicker 0.6s ease-out 1;
        }
      }
      @keyframes sbs-breathe {
        0%, 100% {
          box-shadow: 0 0 0 0 transparent;
        }
        50% {
          box-shadow: 0 0 8px 1.5px rgba(245, 166, 35, 0.32);
          box-shadow: 0 0 8px 1.5px color-mix(in srgb, var(--accent, #f5a623) 32%, transparent);
        }
      }
      @keyframes sbs-pulse-amber {
        0%, 100% {
          box-shadow: 0 0 0 0 transparent;
        }
        50% {
          box-shadow: 0 0 10px 2px rgba(245, 166, 35, 0.48);
          box-shadow: 0 0 10px 2px color-mix(in srgb, var(--accent, #f5a623) 48%, transparent);
        }
      }
      @keyframes sbs-flicker {
        0% { opacity: 1; transform: scale(1); }
        20% { opacity: 0.35; transform: scale(0.92); }
        50% { opacity: 1; transform: scale(1.08); }
        75% { opacity: 0.65; transform: scale(0.97); }
        100% { opacity: 1; transform: scale(1); }
      }
    `}</style>
  )

  if (collapsed) {
    return (
      <>
        {styles}
        <div
          id="sidebar-specs-card"
          role="button"
          tabIndex={0}
          onClick={handleAction}
          onKeyDown={handleKeyDown}
          title={titleText}
          aria-label={ariaLabelText}
          className={`sbs-card sbs-badge sbs-badge-collapsed ${isOnline ? 'sbs-badge-online' : 'sbs-badge-reconnecting'}`}
          style={{
            width: '44px',
            height: '44px',
            minWidth: '44px',
            minHeight: '44px',
            margin: '12px auto 6px',
            borderRadius: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: canClick ? 'pointer' : 'default',
            position: 'relative',
            flexShrink: 0,
            color: 'var(--accent, #f5a623)',
            boxSizing: 'border-box',
          }}
        >
          <span
            className={`sbs-ring-dot ${isOnline ? 'sbs-ring-dot-online' : 'sbs-ring-dot-reconnecting'}`}
            style={{
              top: '5px',
              right: '5px',
            }}
          />
          <svg
            id="sidebar-status-bolt"
            key={totalActive}
            className="sbs-bolt-flicker"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--accent, #f5a623)"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
          </svg>
        </div>
      </>
    )
  }

  return (
    <>
      {styles}
      <div
        id="sidebar-specs-card"
        role="button"
        tabIndex={0}
        onClick={handleAction}
        onKeyDown={handleKeyDown}
        title={titleText}
        aria-label={ariaLabelText}
        className="sbs-card sbs-card-expanded"
        style={{
          padding: '12px 14px',
          borderRadius: '8px',
          background: 'transparent',
          border: '1px solid var(--sidebar-divider, rgba(255, 255, 255, 0.08))',
          marginTop: '16px',
          cursor: canClick ? 'pointer' : 'default',
          boxSizing: 'border-box',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '10px',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              minWidth: 0,
              flex: 1,
            }}
          >
            <div
              className={`sbs-badge ${isOnline ? 'sbs-badge-online' : 'sbs-badge-reconnecting'}`}
              style={{
                width: '30px',
                height: '30px',
                minWidth: '30px',
                minHeight: '30px',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                position: 'relative',
                flexShrink: 0,
              }}
            >
              <span
                className={`sbs-ring-dot ${isOnline ? 'sbs-ring-dot-online' : 'sbs-ring-dot-reconnecting'}`}
                style={{
                  top: '-2px',
                  right: '-2px',
                }}
              />
              <svg
                id="sidebar-status-bolt"
                key={totalActive}
                className="sbs-bolt-flicker"
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--accent, #f5a623)"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
            </div>

            <div
              style={{
                minWidth: 0,
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                gap: '2px',
              }}
            >
              <div
                style={{
                  fontSize: '12.5px',
                  fontWeight: '600',
                  color: '#ffffff',
                  lineHeight: '1.2',
                  overflowWrap: 'anywhere',
                }}
              >
                {isOnline ? `${totalActive} ${totalActive === 1 ? 'task' : 'tasks'} synced` : 'Reconnecting'}
              </div>
              <div
                style={{
                  fontSize: '12px',
                  color: 'var(--sidebar-text, #888888)',
                  opacity: 0.8,
                  lineHeight: '1.2',
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                  overflowWrap: 'anywhere',
                }}
              >
                {backendStatus}
              </div>
            </div>
          </div>
        </div>

        {!isOnline && onRetryConnection && (
          <button
            id="sidebar-retry-connection-button"
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onRetryConnection()
            }}
            onKeyDown={(e) => {
              e.stopPropagation()
            }}
            title="Ping backend to wake up now"
            style={{
              width: '100%',
              height: '32px',
              marginTop: '10px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '12px',
              fontWeight: '600',
              padding: '0 8px',
              borderRadius: '6px',
              background: 'var(--accent, #f5a623)',
              border: '1px solid transparent',
              color: 'var(--accent-text, #000000)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              flexShrink: 0,
              boxSizing: 'border-box',
            }}
            onMouseEnter={e => e.currentTarget.style.opacity = '0.9'}
            onMouseLeave={e => e.currentTarget.style.opacity = '1'}
          >
            Wake up
          </button>
        )}

        {children ? (
          <div
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <div
              style={{
                height: '1px',
                background: 'var(--sidebar-divider, rgba(255, 255, 255, 0.08))',
                marginTop: '10px',
                marginBottom: '8px',
              }}
            />
            {children}
          </div>
        ) : null}
      </div>
    </>
  )
}
