import React from 'react'
import { Search } from 'lucide-react'
import { getDomainMeta } from './domainMeta'

export default function TimelineFilters({
  tasks = [],
  activeDomain,
  onSelectDomain,
  statusFilter,
  setStatusFilter,
  searchQuery,
  setSearchQuery,
}) {
  const basePills = ['all', 'hackathon', 'coursework', 'code', 'general', 'other']
  const customPills = tasks
    .map(t => (t.domain || '').toLowerCase().trim())
    .filter(d => d && !basePills.includes(d))
  const uniquePills = Array.from(new Set([...basePills, ...customPills]))

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: '12px',
        marginBottom: '20px',
        flexWrap: 'wrap',
      }}
    >
      {/* Domain Filter Pills */}
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
        {uniquePills.map(dom => {
          const pillMeta = dom === 'all' ? { label: 'All Domains' } : getDomainMeta(dom)
          const isSelected = activeDomain === dom
          return (
            <button
              key={dom}
              id={`filter-pill-${dom}`}
              onClick={() => onSelectDomain(dom)}
              style={{
                padding: '6px 14px',
                borderRadius: '20px',
                fontSize: '12.5px',
                fontWeight: isSelected ? '700' : '500',
                cursor: 'pointer',
                border: isSelected ? '1px solid #2563eb' : '1px solid #e2e8f0',
                background: isSelected ? '#2563eb' : '#ffffff',
                color: isSelected ? '#ffffff' : '#64748b',
                boxShadow: isSelected ? '0 2px 6px rgba(37, 99, 235, 0.25)' : 'none',
                transition: 'all 0.15s ease',
              }}
            >
              {pillMeta.label}
            </button>
          )
        })}
      </div>

      {/* Search & Status Filters */}
      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
        {/* Status Selector */}
        <div
          style={{
            display: 'flex',
            background: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '8px',
            padding: '2px',
          }}
        >
          {[
            { key: 'all', label: 'All' },
            { key: 'open', label: 'Open' },
            { key: 'urgent', label: 'Urgent' },
            { key: 'completed', label: 'Done' },
          ].map(st => (
            <button
              key={st.key}
              onClick={() => setStatusFilter(st.key)}
              style={{
                padding: '5px 10px',
                borderRadius: '6px',
                border: 'none',
                fontSize: '12px',
                fontWeight: statusFilter === st.key ? '700' : '500',
                background: statusFilter === st.key ? '#f1f5f9' : 'transparent',
                color: statusFilter === st.key ? '#0f172a' : '#64748b',
                cursor: 'pointer',
                transition: 'all 0.1s ease',
              }}
            >
              {st.label}
            </button>
          ))}
        </div>

        {/* Search Box */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            background: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '8px',
            padding: '6px 12px',
            width: '210px',
          }}
        >
          <Search size={14} color="#94a3b8" />
          <input
            type="text"
            placeholder="Search tasks & tags..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            style={{
              border: 'none',
              outline: 'none',
              fontSize: '12.5px',
              color: '#0f172a',
              width: '100%',
              background: 'transparent',
            }}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              style={{
                border: 'none',
                background: 'transparent',
                color: '#94a3b8',
                cursor: 'pointer',
                fontSize: '12px',
                padding: 0,
              }}
            >
              ✕
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
