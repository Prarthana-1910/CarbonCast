import { useMemo, useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useWeeklyForecast168, type Forecast168Point } from '../hooks/useWeeklyForecast168'

interface WeeklyCarbonIntensityChartProps {
  regionCode: string
}

export type EmissionViewMode = 'direct' | 'lifecycle' | 'both'

export default function WeeklyCarbonIntensityChart({ regionCode }: WeeklyCarbonIntensityChartProps) {
  const { data, loading, error, refetch } = useWeeklyForecast168(regionCode)
  const [viewMode, setViewMode] = useState<EmissionViewMode>('both')
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false)
  const [hoveredPoint, setHoveredPoint] = useState<{ point: Forecast168Point; x: number; y: number } | null>(null)
  const [fullscreenHoveredPoint, setFullscreenHoveredPoint] = useState<{ point: Forecast168Point; x: number; y: number } | null>(null)

  // Close on Escape key press when fullscreen is active
  useEffect(() => {
    if (!isFullscreen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsFullscreen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isFullscreen])

  // Dynamic Y-axis maximum scaling based on active view mode
  const maxValue = useMemo(() => {
    if (!data || data.length === 0) return 700

    const validValues: number[] = []
    data.forEach((d) => {
      if ((viewMode === 'direct' || viewMode === 'both') && d.directValue !== null && !isNaN(d.directValue)) {
        validValues.push(d.directValue)
      }
      if ((viewMode === 'lifecycle' || viewMode === 'both') && d.lifecycleValue !== null && !isNaN(d.lifecycleValue)) {
        validValues.push(d.lifecycleValue)
      }
    })

    if (validValues.length === 0) return 700
    const highest = Math.max(...validValues, 0)
    return Math.max(100, Math.ceil(highest / 100) * 100)
  }, [data, viewMode])

  // Summary statistics for direct and lifecycle emissions
  const stats = useMemo(() => {
    if (!data || data.length === 0) {
      return {
        direct: { min: 0, avg: 0, max: 0, count: 0 },
        lifecycle: { min: 0, avg: 0, max: 0, count: 0 }
      }
    }

    const calcSeries = (vals: number[]) => {
      if (vals.length === 0) return { min: 0, avg: 0, max: 0, count: 0 }
      const min = Math.round(Math.min(...vals))
      const max = Math.round(Math.max(...vals))
      const avg = Math.round(vals.reduce((a, b) => a + b, 0) / vals.length)
      return { min, avg, max, count: vals.length }
    }

    const directVals = data
      .map((d) => d.directValue)
      .filter((v): v is number => v !== null && !isNaN(v))

    const lifecycleVals = data
      .map((d) => d.lifecycleValue)
      .filter((v): v is number => v !== null && !isNaN(v))

    return {
      direct: calcSeries(directVals),
      lifecycle: calcSeries(lifecycleVals)
    }
  }, [data])

  const totalPoints = data.length

  // Helper function to build polylines for a given SVG coordinate frame
  const buildPolyline = (
    key: 'directValue' | 'lifecycleValue',
    plotXStart: number,
    plotWidth: number,
    plotYEnd: number,
    plotHeight: number
  ) => {
    if (!data || data.length === 0) return ''
    return data
      .map((d, i) => {
        const val = d[key]
        if (val === null || isNaN(val)) return null
        const x = totalPoints > 1 ? plotXStart + (i / (totalPoints - 1)) * plotWidth : plotXStart
        const clampedVal = Math.max(0, Math.min(maxValue, val))
        const y = plotYEnd - (clampedVal / maxValue) * plotHeight
        return `${x.toFixed(1)},${y.toFixed(1)}`
      })
      .filter((pt): pt is string => pt !== null)
      .join(' ')
  }

  // --- Normal Card Layout Dimensions (viewBox="0 0 340 180") ---
  const normXStart = 34
  const normXEnd = 328
  const normWidth = normXEnd - normXStart
  const normYStart = 16
  const normYEnd = 150
  const normHeight = normYEnd - normYStart

  const normDayMarkers = useMemo(() => {
    if (totalPoints === 0) return []
    const markers: Array<{ dayNum: number; x: number; label: string }> = []
    const daysCount = Math.ceil(totalPoints / 24)
    for (let d = 0; d < daysCount; d++) {
      const pointIndex = d * 24
      const x = totalPoints > 1 ? normXStart + (pointIndex / (totalPoints - 1)) * normWidth : normXStart
      markers.push({ dayNum: d + 1, x, label: `D${d + 1}` })
    }
    return markers
  }, [totalPoints, normXStart, normWidth])

  const normDirectPoints = useMemo(() => {
    if (viewMode !== 'direct' && viewMode !== 'both') return ''
    return buildPolyline('directValue', normXStart, normWidth, normYEnd, normHeight)
  }, [data, viewMode, maxValue, totalPoints, normXStart, normWidth, normYEnd, normHeight])

  const normLifecyclePoints = useMemo(() => {
    if (viewMode !== 'lifecycle' && viewMode !== 'both') return ''
    return buildPolyline('lifecycleValue', normXStart, normWidth, normYEnd, normHeight)
  }, [data, viewMode, maxValue, totalPoints, normXStart, normWidth, normYEnd, normHeight])

  // --- Fullscreen Layout Dimensions (viewBox="0 0 1000 440") ---
  const fsXStart = 60
  const fsXEnd = 960
  const fsWidth = fsXEnd - fsXStart
  const fsYStart = 24
  const fsYEnd = 380
  const fsHeight = fsYEnd - fsYStart

  const fsDayMarkers = useMemo(() => {
    if (totalPoints === 0) return []
    const markers: Array<{ dayNum: number; x: number; label: string; dateStr: string }> = []
    const daysCount = Math.ceil(totalPoints / 24)
    for (let d = 0; d < daysCount; d++) {
      const pointIndex = d * 24
      const x = totalPoints > 1 ? fsXStart + (pointIndex / (totalPoints - 1)) * fsWidth : fsXStart
      const samplePoint = data[pointIndex]
      let dateLabel = `Day ${d + 1}`
      if (samplePoint && samplePoint.time) {
        try {
          const dt = new Date(samplePoint.time)
          dateLabel = `${dt.toLocaleDateString(undefined, { weekday: 'short', month: 'numeric', day: 'numeric' })}`
        } catch {
          dateLabel = `Day ${d + 1}`
        }
      }
      markers.push({ dayNum: d + 1, x, label: `Day ${d + 1}`, dateStr: dateLabel })
    }
    return markers
  }, [data, totalPoints, fsXStart, fsWidth])

  const fsDirectPoints = useMemo(() => {
    if (viewMode !== 'direct' && viewMode !== 'both') return ''
    return buildPolyline('directValue', fsXStart, fsWidth, fsYEnd, fsHeight)
  }, [data, viewMode, maxValue, totalPoints, fsXStart, fsWidth, fsYEnd, fsHeight])

  const fsLifecyclePoints = useMemo(() => {
    if (viewMode !== 'lifecycle' && viewMode !== 'both') return ''
    return buildPolyline('lifecycleValue', fsXStart, fsWidth, fsYEnd, fsHeight)
  }, [data, viewMode, maxValue, totalPoints, fsXStart, fsWidth, fsYEnd, fsHeight])

  // Reusable Mode Toggle Element
  const renderModeToggle = () => (
    <div
      style={{
        display: 'inline-flex',
        padding: '2px',
        borderRadius: '8px',
        backgroundColor: 'var(--toggleInactiveBg)',
        border: '1px solid var(--panelBorder)'
      }}
    >
      {(['direct', 'lifecycle', 'both'] as EmissionViewMode[]).map((mode) => {
        const isActive = viewMode === mode
        const label = mode === 'direct' ? 'Direct' : mode === 'lifecycle' ? 'Lifecycle' : 'Both'
        return (
          <button
            key={mode}
            type="button"
            onClick={() => setViewMode(mode)}
            style={{
              padding: '3px 9px',
              fontSize: '0.72rem',
              fontWeight: isActive ? 600 : 500,
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              backgroundColor: isActive ? 'var(--toggleActiveBg)' : 'transparent',
              color: isActive ? 'var(--panelText)' : 'var(--muted)',
              boxShadow: isActive ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'
            }}
          >
            {label}
          </button>
        )
      })}
    </div>
  )

  // Reusable Stats Badges
  const renderStatBadges = (isExpanded = false) => (
    <div
      style={{
        display: 'flex',
        flexDirection: isExpanded ? 'row' : 'column',
        gap: '6px',
        marginBottom: isExpanded ? '1rem' : '0.75rem',
        flexWrap: 'wrap'
      }}
    >
      {(viewMode === 'direct' || viewMode === 'both') && stats.direct.count > 0 && (
        <div
          style={{
            flex: isExpanded ? 1 : 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: isExpanded ? '6px 12px' : '4px 8px',
            borderRadius: '8px',
            backgroundColor: 'rgba(239, 68, 68, 0.08)',
            border: '1px solid rgba(239, 68, 68, 0.25)',
            fontSize: isExpanded ? '0.8rem' : '0.72rem',
            color: 'var(--panelText)'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
            <span
              style={{
                width: '12px',
                height: '2px',
                borderTop: '2px dashed #EF4444',
                display: 'inline-block'
              }}
            />
            <span style={{ color: '#EF4444' }}>Direct Emissions</span>
          </div>
          <div style={{ display: 'flex', gap: '12px', color: 'var(--subText)' }}>
            <span>Min: <strong>{stats.direct.min}</strong></span>
            <span>Avg: <strong>{stats.direct.avg}</strong></span>
            <span>Max: <strong>{stats.direct.max}</strong></span>
            <span style={{ fontSize: '0.68rem', opacity: 0.8 }}>gCO₂eq/kWh</span>
          </div>
        </div>
      )}

      {(viewMode === 'lifecycle' || viewMode === 'both') && stats.lifecycle.count > 0 && (
        <div
          style={{
            flex: isExpanded ? 1 : 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: isExpanded ? '6px 12px' : '4px 8px',
            borderRadius: '8px',
            backgroundColor: 'rgba(139, 92, 246, 0.08)',
            border: '1px solid rgba(139, 92, 246, 0.25)',
            fontSize: isExpanded ? '0.8rem' : '0.72rem',
            color: 'var(--panelText)'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
            <span
              style={{
                width: '12px',
                height: '2px',
                backgroundColor: '#8B5CF6',
                display: 'inline-block'
              }}
            />
            <span style={{ color: '#8B5CF6' }}>Lifecycle Emissions</span>
          </div>
          <div style={{ display: 'flex', gap: '12px', color: 'var(--subText)' }}>
            <span>Min: <strong>{stats.lifecycle.min}</strong></span>
            <span>Avg: <strong>{stats.lifecycle.avg}</strong></span>
            <span>Max: <strong>{stats.lifecycle.max}</strong></span>
            <span style={{ fontSize: '0.68rem', opacity: 0.8 }}>gCO₂eq/kWh</span>
          </div>
        </div>
      )}
    </div>
  )

  // Reusable Legend
  const renderLegend = () => (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        columnGap: '1.25rem',
        rowGap: '0.45rem',
        marginTop: '0.65rem',
        flexWrap: 'wrap',
        textAlign: 'center'
      }}
    >
      {(viewMode === 'direct' || viewMode === 'both') && (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
          <div style={{ width: '18px', height: '2px', borderTop: '2px dashed #EF4444' }} />
          <span style={{ fontSize: '0.75rem', color: 'var(--subText)', fontWeight: 500 }}>
            Direct Forecast (Hourly)
          </span>
        </div>
      )}

      {(viewMode === 'lifecycle' || viewMode === 'both') && (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
          <div style={{ width: '18px', height: '2px', backgroundColor: '#8B5CF6' }} />
          <span style={{ fontSize: '0.75rem', color: 'var(--subText)', fontWeight: 500 }}>
            Lifecycle Forecast (Hourly)
          </span>
        </div>
      )}

      <div style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>
        Horizon: {Math.round((data.length / 24) * 10) / 10} days ({data.length} hours)
      </div>
    </div>
  )

  return (
    <>
      {/* Standard Card in Drawer */}
      <div
        style={{
          borderRadius: '16px',
          border: '1px solid var(--panelBorder)',
          backgroundColor: 'var(--cardBg)',
          backdropFilter: 'blur(40px) saturate(200%)',
          WebkitBackdropFilter: 'blur(40px) saturate(200%)',
          padding: '1.5rem',
          marginBottom: '1.25rem',
          boxShadow: '0 12px 48px rgba(0, 0, 0, 0.12), 0 4px 16px rgba(0, 0, 0, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.05)',
          position: 'relative',
          overflow: 'hidden'
        }}
      >
        {/* Header with Title, Mode Controls & Expand Button */}
        <div
          style={{
            marginBottom: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '8px'
          }}
        >
          <div>
            <h3
              style={{
                fontSize: '1rem',
                fontWeight: 700,
                color: 'var(--panelText)',
                letterSpacing: '-0.01em',
                margin: 0
              }}
            >
              168-Hour Carbon Intensity Forecast
            </h3>
            <div style={{ fontSize: '0.75rem', color: 'var(--muted)', marginTop: '2px' }}>
              {data.length > 0 ? `${data.length} hourly projections (Forecast168 model)` : 'Multi-day forecast telemetry'}
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {renderModeToggle()}

            {/* Expand / Fullscreen Button */}
            <button
              type="button"
              onClick={() => setIsFullscreen(true)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--muted)',
                cursor: 'pointer',
                padding: '5px',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.15s ease'
              }}
              title="Expand to Fullscreen View"
              aria-label="Expand to Fullscreen"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="15 3 21 3 21 9" />
                <polyline points="9 21 3 21 3 15" />
                <line x1="21" y1="3" x2="14" y2="10" />
                <line x1="3" y1="21" x2="10" y2="14" />
              </svg>
            </button>

            {/* Reload Button */}
            <button
              onClick={() => refetch()}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--muted)',
                cursor: 'pointer',
                padding: '5px',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
              title="Reload 168h forecast"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
              </svg>
            </button>
          </div>
        </div>

        {/* Min / Avg / Max Summary Stats Badges */}
        {!loading && !error && data.length > 0 && renderStatBadges(false)}

        {loading && (
          <div style={{ textAlign: 'center', padding: '2.5rem', color: 'var(--muted)', fontSize: '0.875rem' }}>
            Loading 168-hour forecast from Forecast168...
          </div>
        )}

        {error && !loading && (
          <div style={{ textAlign: 'center', padding: '2rem', color: '#EF4444', fontSize: '0.875rem' }}>
            {error}
          </div>
        )}

        {!loading && !error && data.length === 0 && (
          <div style={{ textAlign: 'center', padding: '2.5rem', color: 'var(--muted)', fontSize: '0.875rem' }}>
            No 168-hour forecast records available for {regionCode}.
          </div>
        )}

        {!loading && !error && data.length > 0 && (
          <div style={{ position: 'relative', width: '100%' }}>
            {/* Tooltip on hover */}
            {hoveredPoint && (
              <div
                style={{
                  position: 'absolute',
                  top: 4,
                  right: 8,
                  padding: '6px 10px',
                  borderRadius: '6px',
                  background: 'rgba(0,0,0,0.85)',
                  color: '#fff',
                  fontSize: '11px',
                  pointerEvents: 'none',
                  zIndex: 10,
                  boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
                  lineHeight: 1.4
                }}
              >
                <div style={{ fontSize: '10px', opacity: 0.75, marginBottom: '2px' }}>
                  {hoveredPoint.point.time ? new Date(hoveredPoint.point.time).toLocaleString() : ''}
                </div>
                {(viewMode === 'direct' || viewMode === 'both') && (
                  <div style={{ color: '#FCA5A5', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#EF4444' }} />
                    Direct:{' '}
                    <strong>
                      {hoveredPoint.point.directValue !== null ? `${Math.round(hoveredPoint.point.directValue)} gCO₂eq/kWh` : 'N/A'}
                    </strong>
                  </div>
                )}
                {(viewMode === 'lifecycle' || viewMode === 'both') && (
                  <div style={{ color: '#C4B5FD', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#8B5CF6' }} />
                    Lifecycle:{' '}
                    <strong>
                      {hoveredPoint.point.lifecycleValue !== null ? `${Math.round(hoveredPoint.point.lifecycleValue)} gCO₂eq/kWh` : 'N/A'}
                    </strong>
                  </div>
                )}
              </div>
            )}

            {/* SVG Chart Wrapper */}
            <div style={{ height: '180px', position: 'relative', width: '100%' }}>
              <svg
                width="100%"
                height="100%"
                viewBox="0 0 340 180"
                style={{ overflow: 'visible' }}
                onMouseLeave={() => setHoveredPoint(null)}
              >
              {/* Horizontal Grid lines */}
              {[0, 1, 2, 3].map((i) => {
                const y = normYStart + i * (normHeight / 3)
                return (
                  <line
                    key={`h-${i}`}
                    x1={normXStart}
                    y1={y}
                    x2={normXEnd}
                    y2={y}
                    stroke="var(--panelBorder)"
                    strokeWidth="1"
                    strokeDasharray="2,2"
                  />
                )
              })}

              {/* Vertical Day Boundary Lines */}
              {normDayMarkers.map((marker, idx) => (
                <g key={`v-${idx}`}>
                  <line
                    x1={marker.x}
                    y1={normYStart}
                    x2={marker.x}
                    y2={normYEnd}
                    stroke="var(--panelBorder)"
                    strokeWidth="1"
                    strokeDasharray="3,3"
                    opacity={0.6}
                  />
                  <text
                    x={marker.x + (idx === normDayMarkers.length - 1 ? -4 : 4)}
                    y={normYEnd + 14}
                    fontSize="9"
                    fill="var(--subText)"
                    textAnchor={idx === normDayMarkers.length - 1 ? 'end' : 'start'}
                  >
                    {marker.label}
                  </text>
                </g>
              ))}

              {/* Lifecycle Line (Violet Solid) */}
              {normLifecyclePoints && (
                <polyline fill="none" stroke="#8B5CF6" strokeWidth="2" points={normLifecyclePoints} />
              )}

              {/* Direct Line (Red Dashed) */}
              {normDirectPoints && (
                <polyline fill="none" stroke="#EF4444" strokeWidth="2" strokeDasharray="4,3" points={normDirectPoints} />
              )}

              {/* Interactive Hover Targets */}
              {data.map((d, i) => {
                if (i % 3 !== 0 && i !== data.length - 1) return null
                const x = totalPoints > 1 ? normXStart + (i / (totalPoints - 1)) * normWidth : normXStart
                const primaryVal =
                  viewMode === 'lifecycle'
                    ? d.lifecycleValue ?? d.directValue ?? 0
                    : d.directValue ?? d.lifecycleValue ?? 0
                const clampedVal = Math.max(0, Math.min(maxValue, primaryVal))
                const y = normYEnd - (clampedVal / maxValue) * normHeight
                return (
                  <circle
                    key={`hit-${i}`}
                    cx={x}
                    cy={y}
                    r="5"
                    fill="transparent"
                    cursor="pointer"
                    onMouseEnter={() => setHoveredPoint({ point: d, x, y })}
                  />
                )
              })}

              {/* Y-axis labels */}
              <text x={normXStart - 5} y={normYStart + 4} fontSize="9" fill="var(--subText)" textAnchor="end">
                {maxValue}
              </text>
              <text x={normXStart - 5} y={normYStart + normHeight / 2 + 3} fontSize="9" fill="var(--subText)" textAnchor="end">
                {Math.round(maxValue / 2)}
              </text>
              <text x={normXStart - 5} y={normYEnd} fontSize="9" fill="var(--subText)" textAnchor="end">
                0
              </text>
            </svg>
          </div>

          {renderLegend()}
        </div>
        )}
      </div>

      {/* Fullscreen Overlay Modal (using createPortal to mount at document.body) */}
      {isFullscreen &&
        createPortal(
          <div
            onClick={(e) => {
              if (e.target === e.currentTarget) {
                setIsFullscreen(false)
              }
            }}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 2500,
              backgroundColor: 'rgba(0, 0, 0, 0.78)',
              backdropFilter: 'blur(20px) saturate(180%)',
              WebkitBackdropFilter: 'blur(20px) saturate(180%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '2rem',
              animation: 'fadeIn 0.2s ease-out'
            }}
          >
            <div
              style={{
                width: '94vw',
                maxWidth: '1240px',
                height: '86vh',
                maxHeight: '780px',
                backgroundColor: 'var(--cardBg)',
                border: '1px solid var(--panelBorder)',
                borderRadius: '24px',
                boxShadow: '0 24px 72px rgba(0,0,0,0.45), 0 8px 32px rgba(0,0,0,0.3)',
                padding: '2rem',
                display: 'flex',
                flexDirection: 'column',
                position: 'relative',
                overflow: 'hidden'
              }}
            >
              {/* Top Bar */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: '1.25rem',
                  gap: '12px'
                }}
              >
                <div>
                  <h2
                    style={{
                      fontSize: '1.35rem',
                      fontWeight: 700,
                      color: 'var(--panelText)',
                      letterSpacing: '-0.02em',
                      margin: 0
                    }}
                  >
                    168-Hour Carbon Intensity Forecast
                  </h2>
                  <div style={{ fontSize: '0.82rem', color: 'var(--muted)', marginTop: '3px' }}>
                    Fullscreen Telemetry · Region {regionCode} · {data.length} hourly forecast horizon
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  {renderModeToggle()}

                  {/* Reload Button in Fullscreen */}
                  <button
                    onClick={() => refetch()}
                    style={{
                      background: 'var(--toggleInactiveBg)',
                      border: '1px solid var(--panelBorder)',
                      color: 'var(--panelText)',
                      cursor: 'pointer',
                      padding: '6px 10px',
                      borderRadius: '8px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '5px',
                      fontSize: '0.78rem',
                      fontWeight: 500
                    }}
                    title="Reload forecast"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
                    </svg>
                    Reload
                  </button>

                  {/* Close ("X") Button */}
                  <button
                    type="button"
                    onClick={() => setIsFullscreen(false)}
                    style={{
                      background: 'var(--toggleInactiveBg)',
                      border: '1px solid var(--panelBorder)',
                      color: 'var(--panelText)',
                      cursor: 'pointer',
                      padding: '6px 10px',
                      borderRadius: '8px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'all 0.15s ease'
                    }}
                    title="Close Fullscreen View (Esc)"
                    aria-label="Close"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              </div>

              {/* Stat Badges in Fullscreen */}
              {renderStatBadges(true)}

              {/* Large SVG Chart Container */}
              <div
                style={{
                  flex: 1,
                  minHeight: 0,
                  position: 'relative',
                  width: '100%',
                  marginTop: '0.5rem'
                }}
              >
                {/* Fullscreen Hover Tooltip */}
                {fullscreenHoveredPoint && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 8,
                      right: 16,
                      padding: '8px 14px',
                      borderRadius: '10px',
                      background: 'rgba(0,0,0,0.88)',
                      color: '#fff',
                      fontSize: '12px',
                      pointerEvents: 'none',
                      zIndex: 20,
                      boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
                      lineHeight: 1.5
                    }}
                  >
                    <div style={{ fontSize: '11px', opacity: 0.8, marginBottom: '4px' }}>
                      {fullscreenHoveredPoint.point.time ? new Date(fullscreenHoveredPoint.point.time).toLocaleString() : ''}
                    </div>
                    {(viewMode === 'direct' || viewMode === 'both') && (
                      <div style={{ color: '#FCA5A5', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#EF4444' }} />
                        Direct:{' '}
                        <strong>
                          {fullscreenHoveredPoint.point.directValue !== null
                            ? `${Math.round(fullscreenHoveredPoint.point.directValue)} gCO₂eq/kWh`
                            : 'N/A'}
                        </strong>
                      </div>
                    )}
                    {(viewMode === 'lifecycle' || viewMode === 'both') && (
                      <div style={{ color: '#C4B5FD', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#8B5CF6' }} />
                        Lifecycle:{' '}
                        <strong>
                          {fullscreenHoveredPoint.point.lifecycleValue !== null
                            ? `${Math.round(fullscreenHoveredPoint.point.lifecycleValue)} gCO₂eq/kWh`
                            : 'N/A'}
                        </strong>
                      </div>
                    )}
                  </div>
                )}

                <svg
                  width="100%"
                  height="100%"
                  viewBox="0 0 1000 440"
                  preserveAspectRatio="none"
                  style={{ overflow: 'visible' }}
                  onMouseLeave={() => setFullscreenHoveredPoint(null)}
                >
                  {/* Horizontal Grid lines */}
                  {[0, 1, 2, 3, 4].map((i) => {
                    const y = fsYStart + i * (fsHeight / 4)
                    return (
                      <line
                        key={`fsh-${i}`}
                        x1={fsXStart}
                        y1={y}
                        x2={fsXEnd}
                        y2={y}
                        stroke="var(--panelBorder)"
                        strokeWidth="1"
                        strokeDasharray="4,4"
                      />
                    )
                  })}

                  {/* Vertical Day Boundary Lines & Date Markers */}
                  {fsDayMarkers.map((marker, idx) => (
                    <g key={`fsv-${idx}`}>
                      <line
                        x1={marker.x}
                        y1={fsYStart}
                        x2={marker.x}
                        y2={fsYEnd}
                        stroke="var(--panelBorder)"
                        strokeWidth="1"
                        strokeDasharray="4,4"
                        opacity={0.7}
                      />
                      <text
                        x={marker.x + (idx === fsDayMarkers.length - 1 ? -6 : 6)}
                        y={fsYEnd + 16}
                        fontSize="11"
                        fontWeight="600"
                        fill="var(--panelText)"
                        textAnchor={idx === fsDayMarkers.length - 1 ? 'end' : 'start'}
                      >
                        {marker.label}
                      </text>
                      <text
                        x={marker.x + (idx === fsDayMarkers.length - 1 ? -6 : 6)}
                        y={fsYEnd + 28}
                        fontSize="10"
                        fill="var(--subText)"
                        textAnchor={idx === fsDayMarkers.length - 1 ? 'end' : 'start'}
                      >
                        {marker.dateStr}
                      </text>
                    </g>
                  ))}

                  {/* Lifecycle Line (Violet Solid) */}
                  {fsLifecyclePoints && (
                    <polyline fill="none" stroke="#8B5CF6" strokeWidth="2.5" points={fsLifecyclePoints} />
                  )}

                  {/* Direct Line (Red Dashed) */}
                  {fsDirectPoints && (
                    <polyline fill="none" stroke="#EF4444" strokeWidth="2.5" strokeDasharray="6,4" points={fsDirectPoints} />
                  )}

                  {/* Fullscreen Interactive Hover Targets (Every point for exact precision) */}
                  {data.map((d, i) => {
                    const x = totalPoints > 1 ? fsXStart + (i / (totalPoints - 1)) * fsWidth : fsXStart
                    const primaryVal =
                      viewMode === 'lifecycle'
                        ? d.lifecycleValue ?? d.directValue ?? 0
                        : d.directValue ?? d.lifecycleValue ?? 0
                    const clampedVal = Math.max(0, Math.min(maxValue, primaryVal))
                    const y = fsYEnd - (clampedVal / maxValue) * fsHeight
                    return (
                      <circle
                        key={`fshit-${i}`}
                        cx={x}
                        cy={y}
                        r="6"
                        fill="transparent"
                        cursor="pointer"
                        onMouseEnter={() => setFullscreenHoveredPoint({ point: d, x, y })}
                      />
                    )
                  })}

                  {/* Y-axis labels */}
                  <text x={fsXStart - 10} y={fsYStart + 5} fontSize="11" fontWeight="600" fill="var(--subText)" textAnchor="end">
                    {maxValue}
                  </text>
                  <text x={fsXStart - 10} y={fsYStart + fsHeight * 0.25 + 4} fontSize="11" fill="var(--subText)" textAnchor="end">
                    {Math.round(maxValue * 0.75)}
                  </text>
                  <text x={fsXStart - 10} y={fsYStart + fsHeight * 0.5 + 4} fontSize="11" fill="var(--subText)" textAnchor="end">
                    {Math.round(maxValue * 0.5)}
                  </text>
                  <text x={fsXStart - 10} y={fsYStart + fsHeight * 0.75 + 4} fontSize="11" fill="var(--subText)" textAnchor="end">
                    {Math.round(maxValue * 0.25)}
                  </text>
                  <text x={fsXStart - 10} y={fsYEnd} fontSize="11" fontWeight="600" fill="var(--subText)" textAnchor="end">
                    0
                  </text>
                </svg>
              </div>

              {/* Fullscreen Footer / Legend */}
              {renderLegend()}
            </div>
          </div>,
          document.body
        )}
    </>
  )
}
