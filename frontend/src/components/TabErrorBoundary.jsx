import React from 'react'

/**
 * Contains render errors and lazy-chunk load failures to one tab so the sidebar and
 * navigation stay usable. Resets when "Try again" is pressed or when resetKey changes
 * (e.g. the user switches tabs). Never shows the raw error text to the user.
 */
export default class TabErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, errorInfo) {
    console.error('[Compass TabErrorBoundary] Tab failed to render:', error, errorInfo)
  }

  componentDidUpdate(prevProps) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false })
    }
  }

  handleRetry = () => {
    if (typeof this.props.onRetry === 'function') this.props.onRetry()
    this.setState({ hasError: false })
  }

  render() {
    if (!this.state.hasError) return this.props.children
    return (
      <div
        role="alert"
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '12px',
          padding: '40px 24px',
          textAlign: 'center',
          color: 'var(--text-secondary)',
        }}
      >
        <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
          This section could not be loaded
        </div>
        <div style={{ fontSize: '13px', maxWidth: '360px', lineHeight: 1.5 }}>
          Something went wrong while showing this tab. Your data is safe. Please try again, or switch to another tab.
        </div>
        <button
          type="button"
          onClick={this.handleRetry}
          style={{
            padding: '10px 18px',
            borderRadius: '8px',
            border: 'none',
            background: 'var(--brand, #f5a623)',
            color: '#ffffff',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            minHeight: '44px',
          }}
        >
          Try again
        </button>
      </div>
    )
  }
}
