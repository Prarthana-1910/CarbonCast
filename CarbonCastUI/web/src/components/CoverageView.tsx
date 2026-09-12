import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import AppSidebar from './AppSidebar'
import { useDataFreshness, type RegionStatus } from '../hooks/useDataFreshness'
import { getRegionDisplayName } from '../utils/regionMapping'

function getOverallStatus(status: RegionStatus): {
  type: 'healthy' | 'degraded' | 'stale'
  label: string
  color: string
} {
  if (status.actuals_stale || status.forecast_missing_or_short) {
    return { type: 'stale', label: 'Stale', color: '#EF4444' }
  }
  if (status.weather_is_fallback || status.weather_stale) {
    return { type: 'degraded', label: 'Degraded', color: '#F59E0B' }
  }
  return { type: 'healthy', label: 'Healthy', color: '#10B981' }
}

function getStatusReasons(status: RegionStatus): string {
  const reasons: string[] = []
  if (status.weather_is_fallback) {
    reasons.push('Weather fallback active (12mo historical)')
  }
  if (status.weather_stale) {
    reasons.push('Weather data >6h stale')
  }
  if (status.actuals_stale) {
    reasons.push('Emissions actuals >48h stale')
  }
  if (status.forecast_missing_or_short) {
    reasons.push('Forecast horizon <160h')
  }
  if (reasons.length === 0) {
    return 'All pipeline feeds healthy'
  }
  return reasons.join(' • ')
}

function formatDateTime(isoString: string | null): string {
  if (!isoString) return '—'
  try {
    const d = new Date(isoString)
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return isoString
  }
}

export default function CoverageView() {
  const navigate = useNavigate()
  const { statusList, loading, error, refetch } = useDataFreshness()
  const [searchTerm, setSearchTerm] = useState('')
  const [filterType, setFilterType] = useState<'all' | 'healthy' | 'degraded' | 'stale'>('all')

  const filteredList = useMemo(() => {
    return statusList.filter((item) => {
      const displayName = getRegionDisplayName(item.region)
      const matchesSearch =
        item.region.toLowerCase().includes(searchTerm.toLowerCase()) ||
        displayName.toLowerCase().includes(searchTerm.toLowerCase())

      if (!matchesSearch) return false

      const status = getOverallStatus(item)
      if (filterType === 'all') return true
      return status.type === filterType
    })
  }, [statusList, searchTerm, filterType])

  const counts = useMemo(() => {
    let healthy = 0
    let degraded = 0
    let stale = 0
    statusList.forEach((item) => {
      const s = getOverallStatus(item)
      if (s.type === 'healthy') healthy++
      else if (s.type === 'degraded') degraded++
      else if (s.type === 'stale') stale++
    })
    return { total: statusList.length, healthy, degraded, stale }
  }, [statusList])

  return (
    <div style={{ position: 'fixed', inset: 0, overflow: 'hidden', display: 'flex' }}>
      <AppSidebar />

      <div
        style={{
          position: 'absolute',
          left: window.innerWidth >= 768 ? '63px' : '0',
          right: 0,
          top: 0,
          bottom: 0,
          overflowY: 'auto',
          padding: '24px 32px',
          background: 'linear-gradient(135deg, rgba(248,250,252,0.6) 0%, rgba(203,213,225,0.4) 100%)'
        }}
        className="coverage-container"
      >
        <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
          {/* Header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '24px',
              flexWrap: 'wrap',
              gap: '16px'
            }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <button
                  onClick={() => navigate('/map')}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '36px',
                    height: '36px',
                    borderRadius: '10px',
                    border: '1px solid var(--panelBorder)',
                    background: 'var(--panelBg)',
                    color: 'var(--panelText)',
                    cursor: 'pointer'
                  }}
                  title="Return to Map"
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M15 18l-6-6 6-6" />
                  </svg>
                </button>
                <h1
                  style={{
                    fontSize: '1.75rem',
                    fontWeight: 700,
                    color: 'var(--panelText)',
                    margin: 0,
                    letterSpacing: '-0.02em'
                  }}
                >
                  Region Coverage & Pipeline Health
                </h1>
              </div>
              <p style={{ margin: '6px 0 0 48px', fontSize: '0.875rem', color: 'var(--muted)' }}>
                Real-time telemetry and operational status for all monitored grid balancing authorities
              </p>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                onClick={() => refetch()}
                disabled={loading}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '8px 16px',
                  borderRadius: '10px',
                  border: '1px solid var(--panelBorder)',
                  background: 'var(--panelBg)',
                  color: 'var(--panelText)',
                  fontSize: '0.875rem',
                  fontWeight: 500,
                  cursor: loading ? 'not-allowed' : 'pointer',
                  opacity: loading ? 0.7 : 1
                }}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }}
                >
                  <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
                </svg>
                {loading ? 'Refreshing...' : 'Refresh Status'}
              </button>
            </div>
          </div>

          {/* Metric summary cards */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '16px',
              marginBottom: '24px'
            }}
          >
            <div
              style={{
                background: 'var(--panelBg)',
                backdropFilter: 'blur(30px)',
                WebkitBackdropFilter: 'blur(30px)',
                border: '1px solid var(--panelBorder)',
                borderRadius: '16px',
                padding: '16px',
                boxShadow: '0 4px 16px rgba(0,0,0,0.06)'
              }}
            >
              <div style={{ fontSize: '0.75rem', color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase' }}>
                Monitored Regions
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--panelText)', marginTop: '4px' }}>
                {counts.total}
              </div>
            </div>

            <div
              style={{
                background: 'var(--panelBg)',
                backdropFilter: 'blur(30px)',
                WebkitBackdropFilter: 'blur(30px)',
                border: '1px solid var(--panelBorder)',
                borderRadius: '16px',
                padding: '16px',
                boxShadow: '0 4px 16px rgba(0,0,0,0.06)'
              }}
            >
              <div style={{ fontSize: '0.75rem', color: '#10B981', fontWeight: 600, textTransform: 'uppercase' }}>
                Healthy Feeds
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#10B981', marginTop: '4px' }}>
                {counts.healthy}
              </div>
            </div>

            <div
              style={{
                background: 'var(--panelBg)',
                backdropFilter: 'blur(30px)',
                WebkitBackdropFilter: 'blur(30px)',
                border: '1px solid var(--panelBorder)',
                borderRadius: '16px',
                padding: '16px',
                boxShadow: '0 4px 16px rgba(0,0,0,0.06)'
              }}
            >
              <div style={{ fontSize: '0.75rem', color: '#F59E0B', fontWeight: 600, textTransform: 'uppercase' }}>
                Degraded (Weather Fallback)
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#F59E0B', marginTop: '4px' }}>
                {counts.degraded}
              </div>
            </div>

            <div
              style={{
                background: 'var(--panelBg)',
                backdropFilter: 'blur(30px)',
                WebkitBackdropFilter: 'blur(30px)',
                border: '1px solid var(--panelBorder)',
                borderRadius: '16px',
                padding: '16px',
                boxShadow: '0 4px 16px rgba(0,0,0,0.06)'
              }}
            >
              <div style={{ fontSize: '0.75rem', color: '#EF4444', fontWeight: 600, textTransform: 'uppercase' }}>
                Stale / Action Required
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#EF4444', marginTop: '4px' }}>
                {counts.stale}
              </div>
            </div>
          </div>

          {/* Search & Filter Toolbar */}
          <div
            style={{
              background: 'var(--panelBg)',
              backdropFilter: 'blur(30px)',
              WebkitBackdropFilter: 'blur(30px)',
              border: '1px solid var(--panelBorder)',
              borderRadius: '16px',
              padding: '12px 16px',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '12px',
              flexWrap: 'wrap'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: '1', minWidth: '240px' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                type="text"
                placeholder="Search by region code or name..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{
                  width: '100%',
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  fontSize: '0.875rem',
                  color: 'var(--panelText)'
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: '6px' }}>
              {(['all', 'healthy', 'degraded', 'stale'] as const).map((type) => (
                <button
                  key={type}
                  onClick={() => setFilterType(type)}
                  style={{
                    padding: '6px 12px',
                    borderRadius: '8px',
                    border: '1px solid var(--panelBorder)',
                    background: filterType === type ? 'var(--buttonBgHover)' : 'transparent',
                    color: filterType === type ? 'var(--panelText)' : 'var(--muted)',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    textTransform: 'capitalize',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease'
                  }}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>

          {/* Table */}
          <div
            style={{
              background: 'var(--panelBg)',
              backdropFilter: 'blur(30px)',
              WebkitBackdropFilter: 'blur(30px)',
              border: '1px solid var(--panelBorder)',
              borderRadius: '16px',
              overflow: 'hidden',
              boxShadow: '0 8px 32px rgba(0,0,0,0.08)'
            }}
          >
            {error && (
              <div style={{ padding: '24px', textAlign: 'center', color: '#EF4444' }}>
                Error loading pipeline status: {error}
              </div>
            )}

            {loading && statusList.length === 0 && (
              <div style={{ padding: '48px', textAlign: 'center', color: 'var(--muted)' }}>
                Loading pipeline telemetry from /v1/DataFreshness...
              </div>
            )}

            {!loading && !error && filteredList.length === 0 && (
              <div style={{ padding: '48px', textAlign: 'center', color: 'var(--muted)' }}>
                No regions matching current search and filter.
              </div>
            )}

            {filteredList.length > 0 && (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
                  <thead>
                    <tr
                      style={{
                        borderBottom: '1px solid var(--panelBorder)',
                        background: 'rgba(0,0,0,0.02)'
                      }}
                    >
                      <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--subText)' }}>Region</th>
                      <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--subText)' }}>Status</th>
                      <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--subText)' }}>Diagnostics & Reason</th>
                      <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--subText)' }}>Weather Source</th>
                      <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--subText)' }}>Latest Actual</th>
                      <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--subText)' }}>Latest Forecast</th>
                      <th style={{ padding: '14px 16px', fontWeight: 600, color: 'var(--subText)', textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredList.map((item) => {
                      const displayName = getRegionDisplayName(item.region)
                      const status = getOverallStatus(item)
                      const reason = getStatusReasons(item)

                      return (
                        <tr
                          key={item.region}
                          style={{
                            borderBottom: '1px solid var(--panelBorder)',
                            transition: 'background 0.15s ease'
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(0,0,0,0.02)')}
                          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                        >
                          <td style={{ padding: '14px 16px' }}>
                            <div style={{ fontWeight: 700, color: 'var(--panelText)' }}>{item.region}</div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--muted)', marginTop: '2px' }}>
                              {displayName}
                            </div>
                          </td>

                          <td style={{ padding: '14px 16px' }}>
                            <span
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '6px',
                                padding: '4px 10px',
                                borderRadius: '9999px',
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                backgroundColor: status.color + '15',
                                border: `1px solid ${status.color}30`,
                                color: status.color
                              }}
                            >
                              <span
                                style={{
                                  width: '6px',
                                  height: '6px',
                                  borderRadius: '50%',
                                  backgroundColor: status.color
                                }}
                              />
                              {status.label}
                            </span>
                          </td>

                          <td style={{ padding: '14px 16px', color: 'var(--panelText)', maxWidth: '320px' }}>
                            <div style={{ fontSize: '0.8125rem', lineHeight: 1.4 }}>{reason}</div>
                          </td>

                          <td style={{ padding: '14px 16px' }}>
                            <span
                              style={{
                                padding: '3px 8px',
                                borderRadius: '6px',
                                fontSize: '0.75rem',
                                fontWeight: 500,
                                background: item.weather_is_fallback ? '#F59E0B20' : 'rgba(0,0,0,0.06)',
                                color: item.weather_is_fallback ? '#D97706' : 'var(--panelText)'
                              }}
                            >
                              {item.weather_source ? item.weather_source.toUpperCase() : 'UNKNOWN'}
                            </span>
                          </td>

                          <td style={{ padding: '14px 16px', fontSize: '0.8125rem', color: 'var(--subText)' }}>
                            {formatDateTime(item.latest_actual_ts)}
                          </td>

                          <td style={{ padding: '14px 16px', fontSize: '0.8125rem', color: 'var(--subText)' }}>
                            {formatDateTime(item.latest_forecast_ts)}
                          </td>

                          <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                            <button
                              onClick={() => navigate(`/zone/${item.region}`)}
                              style={{
                                padding: '6px 12px',
                                borderRadius: '8px',
                                border: '1px solid var(--panelBorder)',
                                background: 'var(--buttonBg)',
                                color: 'var(--panelText)',
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                cursor: 'pointer',
                                transition: 'all 0.15s ease'
                              }}
                              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--buttonBgHover)')}
                              onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--buttonBg)')}
                            >
                              View Map
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
