export type Exercise = {
  id: string
  kind: string
  title: string
  text: string
  display: string
  context: string
  tip: string
  reference_available: boolean
}
export type Metric = {
  code: string
  label: string
  state: string
  value: number | null
  unit: string
  detail: string
}
export type Finding = {
  issue_code: string
  state: string
  start_s: number
  end_s: number
  evidence: string
  suggestion: string
}
export type Measurement = {
  version: string
  exercise_id: string
  comparison_key: string
  duration_s: number
  summary: string
  selection: { start_s: number; end_s: number }
  quality: { warnings: string[]; valid_frames: number; total_frames: number; octave_jumps: number }
  words: { text: string; start_s: number; end_s: number }[]
  syllables: {
    label: string
    start_s: number
    end_s: number
    duration_s: number
    energy_dbfs: number
  }[]
  metrics: Metric[]
  findings: Finding[]
  chart: {
    time_s: number[]
    semitones: (number | null)[]
    f0_hz: (number | null)[]
    energy_dbfs: number[]
    waveform: number[][]
  }
  features: {
    median_f0_hz: number
    pitch_range_st: number
    ending_delta_st: number | null
    word_rate_per_minute: number
  }
  trace: { id: string; status: string; started_at: number; finished_at: number }[]
  reference?: { label: string; result: Measurement; audio_url: string }
}
export type Practice = {
  id: string
  exercise_id: string
  created_at: number
  status: string
  result?: Measurement
  trace?: Measurement['trace']
  error?: string
  audio_url: string
  is_reference: boolean
}
export type Memory = {
  enabled: boolean
  patterns: Record<string, number>
  facts: { practice_id: string; exercise_id: string; summary: string }[]
}

export async function speechApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api/speaking' + path, { credentials: 'same-origin', ...init })
  if (!response.ok) {
    let message = '请求未完成，请重试。'
    try {
      const body = await response.json()
      message = typeof body.detail === 'string' ? body.detail : '输入格式不正确，请检查录音与选区。'
    } catch {
      /* Keep the actionable fallback. */
    }
    throw new Error(message)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}
