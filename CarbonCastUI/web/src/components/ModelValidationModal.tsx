import { useState, useMemo, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useForecastValidation, type ValidationEmissionType, type ValidationPoint } from '../hooks/useForecastValidation'
import { getRegionDisplayName } from '../utils/regionMapping'

interface ModelValidationModalProps {
  regionCode: string
  onClose: () => void
}

export default function ModelValidationModal({ regionCode, onClose }: ModelValidationModalProps) {
  const [emissionType, setEmissionType] = useState<ValidationEmissionType>('direct')
  const [blockIndex, setBlockIndex] = useState<number | 'all'>('all')
  const [hoveredPoint, setHoveredPoint] = useState<{ point: ValidationPoint; x: number; y: number } | null>(null)

  const { data, metrics, loading, error, refetch } = useForecastValidation(regionCode, emissionType)

  // Listen for Escape key to close modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  // Filter points according to selected block (168 hours each) or full 1,680 hours
  const displayPoints = useMemo(() => {
    if (!data || data.length === 0) return []
    if (blockIndex === 'all') return data
    const start = blockIndex * 168
    const end = start + 168
    return data.slice(start, end)
  }, [data, blockIndex])

  // Dynamic max value
  const maxValue = useMemo(() => {
    if (displayPoints.length === 0) return 700
    const vals: number[] = []
    displayPoints.forEach((p) => {
      if (p.actual !== null && !isNaN(p.actual)) vals.push(p.actual)
      if (p.predicted !== null && !isNaN(p.predicted)) vals.push(p.predicted)
    })
    if (vals.length === 0) return 700
    const highest = Math.max(...vals, 0)
    return Math.max(100, Math.ceil(highest / 100) * 100)
  }, [displayPoints])

  // Block-specific computed metrics when viewing a single 168h block
  const activeMetrics = useMemo(() => {
    if (blockIndex === 'all' && metrics) {
      return metrics
    }
    if (displayPoints.length === 0) return { mae: 0, rmse: 0, mape: 0 }

    const errs: number[] = []
    const sqErrs: number[] = []
    const pctErrs: number[] = []

    displayPoints.forEach((p) => {
      if (p.actual !== null && p.predicted !== null) {
        const err = Math.abs(p.actual - p.predicted)
        errs.push(err)
        sqErrs.push(err ** 2)
        if (p.actual > 0) {
          pctErrs.push((err / p.actual) * 100)
        }
      }
    })

    const mae = errs.length ? errs.reduce((a, b) => a + b, 0) / errs.length : 0
    const rmse = sqErrs.length ? Math.sqrt(sqErrs.reduce((a, b) => a + b, 0) / sqErrs.length) : 0
    const mape = pctErrs.length ? pctErrs.reduce((a, b) => a + b, 0) / pctErrs.length : 0

    return {
      mae: Math.round(mae * 100) / 100,
      rmse: Math.round(rmse * 100) / 100,
      mape: Math.round(mape * 100) / 100
    }
  }, [blockIndex, metrics, displayPoints])

  // SVG plotting dimensions
  const plotXStart = 64
  const plotXEnd = 960
  const plotWidth = plotXEnd - plotXStart
  const plotYStart = 24
  const plotYEnd = 370
  const plotHeight = plotYEnd - plotYStart

  const totalPoints = displayPoints.length

  // Build Actual polyline (Solid Blue)
  const actualPolyline = useMemo(() => {
    if (displayPoints.length === 0) return ''
    return displayPoints
      .map((d, i) => {
        if (d.actual === null || isNaN(d.actual)) return null
        const x = totalPoints > 1 ? plotXStart + (i / (totalPoints - 1)) * plotWidth : plotXStart
        const clampedVal = Math.max(0, Math.min(maxValue, d.actual))
        const y = plotYEnd - (clampedVal / maxValue) * plotHeight
        return `${x.toFixed(1)},${y.toFixed(1)}`
      })
      .filter((pt): pt is string => pt !== null)
      .join(' ')
  }, [displayPoints, totalPoints, plotXStart, plotWidth, plotYEnd, plotHeight, maxValue])

  // Build Predicted polyline (Dashed Line)
  const predictedPolyline = useMemo(() => {
    if (displayPoints.length === 0) return ''
    return displayPoints
      .map((d, i) => {
        if (d.predicted === null || isNaN(d.predicted)) return null
        const x = totalPoints > 1 ? plotXStart + (i / (totalPoints - 1)) * plotWidth : plotXStart
        const clampedVal = Math.max(0, Math.min(maxValue, d.predicted))
        const y = plotYEnd - (clampedVal / maxValue) * plotHeight
        return `${x.toFixed(1)},${y.toFixed(1)}`
      })
      .filter((pt): pt is string => pt !== null)
      .join(' ')
  }, [displayPoints, totalPoints, plotXStart, plotWidth, plotYEnd, plotHeight, maxValue])

  // Compute boundary tick markers
  const markers = useMemo(() => {
    if (totalPoints === 0) return []
    const list: Array<{ x: number; label: string }> = []
    const step = blockIndex === 'all' ? 168 : 24
    const count = Math.ceil(totalPoints / step)
    for (let s = 0; s < count; s++) {
      const idx = s * step
      const x = totalPoints > 1 ? plotXStart + (idx / (totalPoints - 1)) * plotWidth : plotXStart
      const lbl = blockIndex === 'all' ? `W${s + 1}` : `D${s + 1}`
      list.push({ x, label: lbl })
    }
    return list
  }, [totalPoints, blockIndex, plotXStart, plotWidth])

  const regionName = getRegionDisplayName(regionCode)
  const predictedColor = emissionType === 'direct' ? '#EF4444' : '#8B5CF6'

  return createPortal(
    <div
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose()
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
          height: '88vh',
          maxHeight: '800px',
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
        {/* Top Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '1rem',
            gap: '12px'
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h2
                style={{
                  fontSize: '1.35rem',
                  fontWeight: 700,
                  color: 'var(--panelText)',
                  letterSpacing: '-0.02em',
                  margin: 0
                }}
              >
                Model Validation & Test Evaluation
              </h2>
              <span
                style={{
                  padding: '2px 8px',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(59, 130, 246, 0.15)',
                  color: '#3B82F6',
                  fontSize: '0.75rem',
                  fontWeight: 600
                }}
              >
                Actual vs. Predicted
              </span>
            </div>
            <div style={{ fontSize: '0.82rem', color: 'var(--muted)', marginTop: '3px' }}>
              {regionName} ({regionCode}) · Static Test Dataset ({data.length} total hourly evaluations)
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {/* Emission Type Toggle */}
            <div
              style={{
                display: 'inline-flex',
                padding: '2px',
                borderRadius: '8px',
                backgroundColor: 'var(--toggleInactiveBg)',
                border: '1px solid var(--panelBorder)'
              }}
            >
              {(['direct', 'lifecycle'] as ValidationEmissionType[]).map((type) => {
                const isActive = emissionType === type
                return (
                  <button
                    key={type}
                    type="button"
                    onClick={() => setEmissionType(type)}
                    style={{
                      padding: '4px 11px',
                      fontSize: '0.75rem',
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
                    {type === 'direct' ? 'Direct Emissions' : 'Lifecycle Emissions'}
                  </button>
                )
              })}
            </div>

            {/* Reload Button */}
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
              title="Reload validation data"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
              </svg>
              Reload
            </button>

            {/* Close ("X") Button */}
            <button
              type="button"
              onClick={onClose}
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
              title="Close (Esc)"
              aria-label="Close"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* Validation Accuracy Metrics Summary Row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '10px',
            marginBottom: '0.85rem',
            padding: '8px 14px',
            borderRadius: '10px',
            backgroundColor: 'var(--toggleInactiveBg)',
            border: '1px solid var(--panelBorder)'
          }}
        >
          {/* Accuracy Metrics */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '0.82rem' }}>
            <div>
              <span style={{ color: 'var(--muted)', marginRight: '5px' }}>MAE:</span>
              <strong style={{ color: 'var(--panelText)' }}>{activeMetrics?.mae ?? '—'}</strong>
              <span style={{ fontSize: '0.7rem', color: 'var(--muted)', marginLeft: '3px' }}>gCO₂eq/kWh</span>
            </div>
            <div style={{ width: '1px', height: '14px', backgroundColor: 'var(--panelBorder)' }} />
            <div>
              <span style={{ color: 'var(--muted)', marginRight: '5px' }}>RMSE:</span>
              <strong style={{ color: 'var(--panelText)' }}>{activeMetrics?.rmse ?? '—'}</strong>
              <span style={{ fontSize: '0.7rem', color: 'var(--muted)', marginLeft: '3px' }}>gCO₂eq/kWh</span>
            </div>
            <div style={{ width: '1px', height: '14px', backgroundColor: 'var(--panelBorder)' }} />
            <div>
              <span style={{ color: 'var(--muted)', marginRight: '5px' }}>MAPE:</span>
              <strong style={{ color: 'var(--panelText)' }}>{activeMetrics?.mape !== null ? `${activeMetrics.mape}%` : '—'}</strong>
            </div>
          </div>

          {/* Horizon Block Selector (10 consecutive 168-hour test weeks) */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>Window:</span>
            <div
              style={{
                display: 'inline-flex',
                borderRadius: '6px',
                border: '1px solid var(--panelBorder)',
                overflow: 'hidden'
              }}
            >
              <button
                type="button"
                onClick={() => setBlockIndex('all')}
                style={{
                  padding: '3px 8px',
                  fontSize: '0.72rem',
                  border: 'none',
                  cursor: 'pointer',
                  backgroundColor: blockIndex === 'all' ? 'var(--toggleActiveBg)' : 'transparent',
                  color: blockIndex === 'all' ? 'var(--panelText)' : 'var(--muted)',
                  fontWeight: blockIndex === 'all' ? 600 : 400
                }}
              >
                All (10 Wks)
              </button>
              {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((b) => (
                <button
                  key={b}
                  type="button"
                  onClick={() => setBlockIndex(b)}
                  style={{
                    padding: '3px 7px',
                    fontSize: '0.72rem',
                    border: 'none',
                    borderLeft: '1px solid var(--panelBorder)',
                    cursor: 'pointer',
                    backgroundColor: blockIndex === b ? 'var(--toggleActiveBg)' : 'transparent',
                    color: blockIndex === b ? 'var(--panelText)' : 'var(--muted)',
                    fontWeight: blockIndex === b ? 600 : 400
                  }}
                  title={`Test Week ${b + 1} (168 hours)`}
                >
                  W{b + 1}
                </button>
              ))}
            </div>
          </div>
        </div>

        {loading && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
            Loading model test validation data from CI_forecast_data...
          </div>
        )}

        {error && !loading && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#EF4444' }}>
            {error}
          </div>
        )}

        {!loading && !error && displayPoints.length === 0 && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)' }}>
            No validation data records available for {regionCode}.
          </div>
        )}

        {!loading && !error && displayPoints.length > 0 && (
          <div style={{ flex: 1, minHeight: 0, position: 'relative', width: '100%', marginTop: '0.25rem' }}>
            {/* Tooltip on hover */}
            {hoveredPoint && (
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
                  {hoveredPoint.point.datetime ? new Date(hoveredPoint.point.datetime).toLocaleString() : ''}
                </div>
                <div style={{ color: '#93C5FD', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#3B82F6' }} />
                  Actual:{' '}
                  <strong>
                    {hoveredPoint.point.actual !== null ? `${Math.round(hoveredPoint.point.actual)} gCO₂eq/kWh` : 'N/A'}
                  </strong>
                </div>
                <div style={{ color: emissionType === 'direct' ? '#FCA5A5' : '#C4B5FD', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: predictedColor }} />
                  Forecasted:{' '}
                  <strong>
                    {hoveredPoint.point.predicted !== null ? `${Math.round(hoveredPoint.point.predicted)} gCO₂eq/kWh` : 'N/A'}
                  </strong>
                </div>
                {hoveredPoint.point.actual !== null && hoveredPoint.point.predicted !== null && (
                  <div style={{ fontSize: '10px', color: 'rgba(255,255,255,0.7)', marginTop: '2px' }}>
                    Error: Δ {Math.round(Math.abs(hoveredPoint.point.actual - hoveredPoint.point.predicted))} gCO₂eq/kWh
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
              onMouseLeave={() => setHoveredPoint(null)}
            >
              {/* Horizontal Grid lines */}
              {[0, 1, 2, 3, 4].map((i) => {
                const y = plotYStart + i * (plotHeight / 4)
                return (
                  <line
                    key={`vh-${i}`}
                    x1={plotXStart}
                    y1={y}
                    x2={plotXEnd}
                    y2={y}
                    stroke="var(--panelBorder)"
                    strokeWidth="1"
                    strokeDasharray="4,4"
                  />
                )
              })}

              {/* Boundary Lines & Date Markers */}
              {markers.map((marker, idx) => (
                <g key={`vm-${idx}`}>
                  <line
                    x1={marker.x}
                    y1={plotYStart}
                    x2={marker.x}
                    y2={plotYEnd}
                    stroke="var(--panelBorder)"
                    strokeWidth="1"
                    strokeDasharray="4,4"
                    opacity={0.7}
                  />
                  <text
                    x={marker.x + (idx === markers.length - 1 ? -6 : 6)}
                    y={plotYEnd + 16}
                    fontSize="11"
                    fontWeight="600"
                    fill="var(--panelText)"
                    textAnchor={idx === markers.length - 1 ? 'end' : 'start'}
                  >
                    {marker.label}
                  </text>
                </g>
              ))}

              {/* Actual Line (Solid Blue) */}
              {actualPolyline && (
                <polyline fill="none" stroke="#3B82F6" strokeWidth="2.5" points={actualPolyline} />
              )}

              {/* Predicted Line (Dashed) */}
              {predictedPolyline && (
                <polyline
                  fill="none"
                  stroke={predictedColor}
                  strokeWidth="2.5"
                  strokeDasharray="6,4"
                  points={predictedPolyline}
                />
              )}

              {/* Interactive Hover Circles (Sampled for responsiveness) */}
              {displayPoints.map((d, i) => {
                if (totalPoints > 400 && i % 2 !== 0 && i !== totalPoints - 1) return null
                const x = totalPoints > 1 ? plotXStart + (i / (totalPoints - 1)) * plotWidth : plotXStart
                const val = d.actual ?? d.predicted ?? 0
                const clampedVal = Math.max(0, Math.min(maxValue, val))
                const y = plotYEnd - (clampedVal / maxValue) * plotHeight
                return (
                  <circle
                    key={`vhit-${i}`}
                    cx={x}
                    cy={y}
                    r="6"
                    fill="transparent"
                    cursor="pointer"
                    onMouseEnter={() => setHoveredPoint({ point: d, x, y })}
                  />
                )
              })}

              {/* Y-axis labels */}
              <text x={plotXStart - 10} y={plotYStart + 5} fontSize="11" fontWeight="600" fill="var(--subText)" textAnchor="end">
                {maxValue}
              </text>
              <text x={plotXStart - 10} y={plotYStart + plotHeight * 0.25 + 4} fontSize="11" fill="var(--subText)" textAnchor="end">
                {Math.round(maxValue * 0.75)}
              </text>
              <text x={plotXStart - 10} y={plotYStart + plotHeight * 0.5 + 4} fontSize="11" fill="var(--subText)" textAnchor="end">
                {Math.round(maxValue * 0.5)}
              </text>
              <text x={plotXStart - 10} y={plotYStart + plotHeight * 0.75 + 4} fontSize="11" fill="var(--subText)" textAnchor="end">
                {Math.round(maxValue * 0.25)}
              </text>
              <text x={plotXStart - 10} y={plotYEnd} fontSize="11" fontWeight="600" fill="var(--subText)" textAnchor="end">
                0
              </text>
            </svg>
          </div>
        )}

        {/* Legend */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: '2rem',
            marginTop: '0.85rem',
            flexWrap: 'wrap'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <div style={{ width: '22px', height: '2px', backgroundColor: '#3B82F6' }} />
            <span style={{ fontSize: '0.8rem', color: 'var(--subText)', fontWeight: 500 }}>
              Actual Carbon Intensity
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <div style={{ width: '22px', height: '2px', borderTop: `2px dashed ${predictedColor}` }} />
            <span style={{ fontSize: '0.8rem', color: 'var(--subText)', fontWeight: 500 }}>
              Model Forecast ({emissionType === 'direct' ? 'Direct' : 'Lifecycle'})
            </span>
          </div>

          <div style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>
            Showing {displayPoints.length} of {data.length} evaluation hours
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}
