import React from 'react'
import Logo from './Logo'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('[Compass ErrorBoundary] Uncaught error:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
    if (typeof window !== 'undefined') {
      window.location.href = '/'
    }
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null })
    if (typeof window !== 'undefined') {
      window.location.reload()
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: '100vh',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--bg-app, #0f172a)',
            color: 'var(--text-primary, #f8fafc)',
            padding: '24px',
            fontFamily: 'system-ui, -apple-system, sans-serif',
            textAlign: 'center',
          }}
        >
          <div
            style={{
              maxWidth: '480px',
              padding: '32px',
              borderRadius: '16px',
              background: 'var(--bg-card, #1e293b)',
              border: '1px solid var(--border, #334155)',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)',
            }}
          >
            <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'center' }}>
              <Logo size={48} alt="Compass logo" />
            </div>
            <h1 style={{ fontSize: '20px', fontWeight: 700, margin: '0 0 8px 0' }}>
              Something went wrong
            </h1>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary, #94a3b8)', margin: '0 0 20px 0', lineHeight: 1.5 }}>
              Compass encountered an unexpected error while rendering this view. Your session and data remain safe.
            </p>
            {this.state.error && (
              <pre
                style={{
                  background: 'rgba(0, 0, 0, 0.3)',
                  padding: '10px 12px',
                  borderRadius: '8px',
                  fontSize: '11px',
                  color: '#ef4444',
                  textAlign: 'left',
                  overflowX: 'auto',
                  maxHeight: '120px',
                  marginBottom: '20px',
                }}
              >
                {this.state.error.message || String(this.state.error)}
              </pre>
            )}
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
              <button
                type="button"
                onClick={this.handleReload}
                style={{
                  padding: '10px 18px',
                  borderRadius: '8px',
                  border: '1px solid var(--border, #334155)',
                  background: 'transparent',
                  color: 'var(--text-primary, #f8fafc)',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Reload Tab
              </button>
              <button
                type="button"
                onClick={this.handleReset}
                style={{
                  padding: '10px 18px',
                  borderRadius: '8px',
                  border: 'none',
                  background: 'var(--brand, #f5a623)',
                  color: 'var(--accent-text, #1b1a17)fff',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Return to Dashboard
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
