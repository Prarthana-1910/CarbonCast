import { useState, useEffect, useCallback } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000')

export interface RegionStatus {
  region: string
  latest_actual_ts: string | null
  latest_weather_created: string | null
  latest_forecast_ts: string | null
  weather_source: string | null
  weather_is_fallback: boolean
  actuals_stale: boolean
  weather_stale: boolean
  forecast_missing_or_short: boolean
}

export interface DataFreshnessResponse {
  emissions: Array<{ region: string; last_ts: string | null }>
  weather_forecasts: Array<{ region: string; last_forecast_created: string | null }>
  forecasts: Array<{ region: string; last_ts: string | null }>
  status: RegionStatus[]
  carbon_cast_version: string
}

export function useDataFreshness(regionCode?: string) {
  const [data, setData] = useState<DataFreshnessResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const url = new URL(`${API_BASE}/v1/DataFreshness`)
      if (regionCode && regionCode !== 'all') {
        url.searchParams.append('region_code', regionCode)
      }
      const res = await fetch(url.toString())
      if (!res.ok) {
        throw new Error(`Failed to fetch data freshness: HTTP ${res.status}`)
      }
      const json: DataFreshnessResponse = await res.json()
      setData(json)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error fetching data freshness'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [regionCode])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return {
    data,
    statusList: data?.status || [],
    loading,
    error,
    refetch: fetchData
  }
}
