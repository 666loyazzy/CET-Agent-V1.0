// Local vocab API client (V2). Same-origin fetches — Vite dev proxies /api to :8000.

export interface WordDto {
  id: number
  en: string
  zh: string
  zh_full: string
  list_no: number
  index_in_list: number
  review?: ReviewDto | null
}

export interface ReviewDto {
  total_num: number
  forget_num: number
  rate: number
  history: string
  flag: number
  last_reviewed_at: string | null
  next_due_at: string | null
}

export interface BookDto {
  id: number
  code: string
  name_zh: string
  total_words: number
}

export interface ListSummaryDto {
  list_no: number
  size: number
  reviewed: number
  avg_forget_rate: number | null
  recent_forget_rate: number | null
  ebbinghaus_stage: number
  last_review_date: string | null
  days_until_due: number
  due: boolean
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`GET ${url} -> ${res.status}`)
  return res.json() as Promise<T>
}

export async function fetchBooks(): Promise<BookDto[]> {
  return getJson('/api/vocab/books')
}

export async function fetchLists(book: string): Promise<ListSummaryDto[]> {
  return getJson(`/api/vocab/lists?book=${encodeURIComponent(book)}`)
}

export async function fetchList(book: string, listNo: number): Promise<WordDto[]> {
  const data = await getJson<{ words: WordDto[] }>(
    `/api/vocab/list/${encodeURIComponent(book)}/${listNo}`,
  )
  return data.words
}

export async function fetchWord(book: string, wordEn: string): Promise<WordDto | null> {
  try {
    return await getJson<WordDto>(
      `/api/vocab/word/${encodeURIComponent(book)}/${encodeURIComponent(wordEn)}`,
    )
  } catch {
    return null
  }
}

export async function submitReview(wordId: number, remembered: boolean): Promise<ReviewDto> {
  const res = await fetch('/api/vocab/review', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ word_id: wordId, remembered }),
  })
  if (!res.ok) throw new Error(`POST /api/vocab/review -> ${res.status}`)
  return res.json()
}

// Dictation submits results by English spelling (it loads words from a
// static wordlist, not the DB, so it doesn't have word_ids on hand).
export async function submitReviewByEn(
  book: string,
  en: string,
  remembered: boolean,
): Promise<{ word_id: number; total_num: number; forget_num: number; rate: number; history: string }> {
  const res = await fetch('/api/vocab/review/by-en', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ book, en, remembered }),
  })
  if (!res.ok) throw new Error(`POST /api/vocab/review/by-en -> ${res.status}`)
  return res.json()
}

// Flag values: -1 重难词, 0 default, 1 太简单, 2 已掌握. flag>=2 removes
// the word from typing/dictation queues and counts it as mastered.
export async function setReviewFlag(
  args: { word_id: number; flag: number } | { book: string; en: string; flag: number },
): Promise<{ word_id: number; flag: number }> {
  const res = await fetch('/api/vocab/review/flag', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  })
  if (!res.ok) throw new Error(`POST /api/vocab/review/flag -> ${res.status}`)
  return res.json()
}

export async function fetchStats(book?: string): Promise<{
  book: string | null
  total_words: number
  reviewed: number
  mastered: number
  avg_forget_rate: number | null
}> {
  const q = book ? `?book=${encodeURIComponent(book)}` : ''
  return getJson(`/api/vocab/stats${q}`)
}

export interface TodayList {
  list_no: number
  ebbinghaus_stage: number
  last_review_date: string | null
  hit_reason: string
}

export interface TodayResponse {
  book: string
  date: string
  lists: TodayList[]
  heavy_words: unknown[]
}

export async function fetchToday(book: string): Promise<TodayResponse> {
  return getJson(`/api/vocab/today?book=${encodeURIComponent(book)}`)
}

export interface ListReviewResult {
  book: string
  list_no: number
  session_rate: number
  remembered: boolean
  ebbinghaus_stage: number
  last_review_date: string | null
  next_due_date: string
  days_until_due: number
}

export async function submitListReview(
  book: string,
  listNo: number,
): Promise<ListReviewResult> {
  const res = await fetch('/api/vocab/review/list', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ book, list_no: listNo }),
  })
  if (!res.ok) throw new Error(`POST /api/vocab/review/list -> ${res.status}`)
  return res.json()
}
