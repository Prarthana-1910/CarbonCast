import { useState, useEffect, useCallback, useRef } from 'react'
import { convertToApiRegionCode } from '../utils/regionMapping'

const API_BASE = import.meta.env.VITE_API_BASE_URL || (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000')

export type ValidationEmissionType = 'direct' | 'lifecycle'

export interface ValidationPoint {
  datetime: string
  actual: number | null
  predicted: number | null
}

export interface ValidationMetrics {
  mae: number | null
  rmse: number | null
  mape: number | null
}

interface ValidationCacheEntry {
  data: ValidationPoint[]
  metrics: ValidationMetrics | null
  timestamp: number
}

// Isolated cache for validation datasets
const validationCache = new Map<string, ValidationCacheEntry>()
const VALIDATION_CACHE_TTL = 30 * 60 * 1000 // 30 minutes

export function useForecastValidation(
  regionCode: string | undefined,
  emissionType: ValidationEmissionType = 'direct'
) {
  const [data, setData] = useState<ValidationPoint[]>([])
  const [metrics, setMetrics] = useState<ValidationMetrics | null>(null)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const fetchValidation = useCallback(async () => {
    if (!regionCode) {
      setData([])
      setMetrics(null)
      return
    }

    const apiRegionCode = convertToApiRegionCode(regionCode)
    const cacheKey = `validation_${apiRegionCode}_${emissionType}`

    const cached = validationCache.get(cacheKey)
    if (cached && Date.now() - cached.timestamp < VALIDATION_CACHE_TTL) {
      setData(cached.data)
      setMetrics(cached.metrics)
      setLoading(false)
      setError(null)
      return
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller

    setLoading(true)
    setError(null)

    try {
      const url = `${API_BASE}/v1/ForecastValidation?region=${encodeURIComponent(apiRegionCode)}&emissionType=${encodeURIComponent(emissionType)}`
      const res = await fetch(url, { signal: controller.signal })

      if (!res.ok) {
        if (res.status === 404) {
          throw new Error(`No test validation dataset found for ${regionCode} (${emissionType})`)
        }
        throw new Error(`HTTP error ${res.status}`)
      }

      const json = await res.json()
      const rawList = Array.isArray(json?.data) ? json.data : []
      const metricsData: ValidationMetrics | null = json?.metrics || null

      const mappedPoints: ValidationPoint[] = rawList.map((row: Record<string, unknown>) => ({
        datetime: String(row.datetime || ''),
        actual: typeof row.actual === 'number' ? row.actual : (row.actual !== null && row.actual !== undefined ? parseFloat(String(row.actual)) : null),
        predicted: typeof row.predicted === 'number' ? row.predicted : (row.predicted !== null && row.predicted !== undefined ? parseFloat(String(row.predicted)) : null)
      }))

      validationCache.set(cacheKey, {
        data: mappedPoints,
        metrics: metricsData,
        timestamp: Date.now()
      })

      setData(mappedPoints)
      setMetrics(metricsData)
    } catch (err: unknown) {
      if ((err as Error)?.name === 'AbortError') return
      const msg = err instanceof Error ? err.message : 'Error fetching validation data'
      setError(msg)
      setData([])
      setMetrics(null)
    } finally {
      setLoading(false)
    }
  }, [regionCode, emissionType])

  useEffect(() => {
    fetchValidation()
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [fetchValidation])

  return {
    data,
    metrics,
    loading,
    error,
    refetch: fetchValidation
  }
}
