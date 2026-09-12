import { useState, useEffect, useCallback, useRef } from 'react'
import { convertToApiRegionCode } from '../utils/regionMapping'

const API_BASE = import.meta.env.VITE_API_BASE_URL || (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000')

export const EMISSION_FACTOR_DIRECT = 'direct' as const
export const EMISSION_FACTOR_LIFECYCLE = 'lifecycle' as const

export type EmissionFactorType = typeof EMISSION_FACTOR_DIRECT | typeof EMISSION_FACTOR_LIFECYCLE

export interface WeeklyForecastSeriesPoint {
  time: string
  creationTime: string
  value: number | null
  unit: string
  emissionType: EmissionFactorType
}

export interface Forecast168Point {
  time: string
  creationTime: string
  directValue: number | null
  lifecycleValue: number | null
  unit: string
}

interface CacheEntry {
  data: Forecast168Point[]
  directData: WeeklyForecastSeriesPoint[]
  lifecycleData: WeeklyForecastSeriesPoint[]
  timestamp: number
}

// Dedicated isolated cache for 168-hour forecasts to prevent collision with daily 24h timeline cache
const weeklyMemoryCache = new Map<string, CacheEntry>()
const WEEKLY_CACHE_TTL = 30 * 60 * 1000 // 30 minutes

export function useWeeklyForecast168(regionCode: string | undefined) {
  const [data, setData] = useState<Forecast168Point[]>([])
  const [directData, setDirectData] = useState<WeeklyForecastSeriesPoint[]>([])
  const [lifecycleData, setLifecycleData] = useState<WeeklyForecastSeriesPoint[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const fetch168Forecast = useCallback(async () => {
    if (!regionCode) {
      setData([])
      setDirectData([])
      setLifecycleData([])
      return
    }

    const apiRegionCode = convertToApiRegionCode(regionCode)
    const cacheKey = `weekly_forecast168_${apiRegionCode}`

    // Check isolated weekly cache
    const cached = weeklyMemoryCache.get(cacheKey)
    if (cached && Date.now() - cached.timestamp < WEEKLY_CACHE_TTL) {
      setData(cached.data)
      setDirectData(cached.directData)
      setLifecycleData(cached.lifecycleData)
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
      const url = `${API_BASE}/v1/CarbonIntensityForecasts?regionCode=${encodeURIComponent(apiRegionCode)}&forecastPeriod=168h`
      const res = await fetch(url, { signal: controller.signal })

      if (!res.ok) {
        throw new Error(`HTTP error ${res.status}`)
      }

      const json = await res.json()
      const rawList = Array.isArray(json?.data) ? json.data : []

      // Sort raw list chronologically
      const sortedList = [...rawList].sort((a: Record<string, unknown>, b: Record<string, unknown>) => {
        const timeA = new Date((a['UTC time'] || a['time'] || 0) as string | number).getTime()
        const timeB = new Date((b['UTC time'] || b['time'] || 0) as string | number).getTime()
        return timeA - timeB
      })

      const parseNumber = (val: unknown): number | null => {
        if (val === null || val === undefined || val === '') return null
        const num = typeof val === 'number' ? val : parseFloat(String(val))
        return isNaN(num) ? null : num
      }

      const mappedPoints: Forecast168Point[] = []
      const mappedDirect: WeeklyForecastSeriesPoint[] = []
      const mappedLifecycle: WeeklyForecastSeriesPoint[] = []

      for (const row of sortedList) {
        const time = (row['UTC time'] || row['time'] || '') as string
        const creationTime = (row['creation_time (UTC)'] || '') as string
        const unit = (row['carbon_intensity_unit'] || row['cabon_intensity_unit'] || 'gCO2eq/kWh') as string

        let direct: number | null = null
        let lifecycle: number | null = null

        // Check for explicit emission_factor_type in row (if un-pivoted)
        const factorType = row['emission_factor_type']
        if (factorType === EMISSION_FACTOR_DIRECT) {
          direct = parseNumber(row['value'] ?? row['carbon_intensity'] ?? row['carbon_intensity_avg_direct'])
        } else if (factorType === EMISSION_FACTOR_LIFECYCLE) {
          lifecycle = parseNumber(row['value'] ?? row['carbon_intensity'] ?? row['carbon_intensity_avg_lifecycle'])
        } else {
          // Standard endpoint format: row contains both fields
          direct = parseNumber(row['carbon_intensity_avg_direct'])
          lifecycle = parseNumber(row['carbon_intensity_avg_lifecycle'])
        }

        mappedPoints.push({
          time,
          creationTime,
          directValue: direct,
          lifecycleValue: lifecycle,
          unit
        })

        mappedDirect.push({
          time,
          creationTime,
          value: direct,
          unit,
          emissionType: EMISSION_FACTOR_DIRECT
        })

        mappedLifecycle.push({
          time,
          creationTime,
          value: lifecycle,
          unit,
          emissionType: EMISSION_FACTOR_LIFECYCLE
        })
      }

      // Update cache
      weeklyMemoryCache.set(cacheKey, {
        data: mappedPoints,
        directData: mappedDirect,
        lifecycleData: mappedLifecycle,
        timestamp: Date.now()
      })

      setData(mappedPoints)
      setDirectData(mappedDirect)
      setLifecycleData(mappedLifecycle)
    } catch (err: unknown) {
      if ((err as Error)?.name === 'AbortError') return
      const message = err instanceof Error ? err.message : 'Error fetching 168-hour forecast'
      setError(message)
      setData([])
      setDirectData([])
      setLifecycleData([])
    } finally {
      setLoading(false)
    }
  }, [regionCode])

  useEffect(() => {
    fetch168Forecast()
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [fetch168Forecast])

  return {
    directData,
    lifecycleData,
    data,
    loading,
    error,
    refetch: fetch168Forecast
  }
}
