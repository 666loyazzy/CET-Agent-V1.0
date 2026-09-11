// Parses `frontend/static/words-cet{4,6}.txt` into [en, zh] pairs.
// Mirrors backend/db/seed.py::parse_wordlist (Python), which itself was
// ported from the original app.js parseWordlist. Kept as a client-side
// utility so the click-effect can load words without a DB round-trip.

type Pair = [string, string]

const POS_RE = /^(?:n|v|adj|adv|prep|pron|conj|art)\.\s*/i
const CUT_RE = /^([^，,；;]+?)(?=\s+(?:n|v|adj|adv|prep|pron|conj|art)\.|[，,；;]|$)/i

const _cache: Record<string, Pair[]> = {}

export function parseWordlist(text: string): Pair[] {
  const out: Pair[] = []
  for (const line of text.split(/\r?\n/)) {
    const idx = line.indexOf('\t')
    if (idx < 1) continue
    const en = line.slice(0, idx).trim()
    const rawZh = line.slice(idx + 1).trim()
    if (!en || !rawZh) continue
    const cleaned = rawZh.replace(POS_RE, '').trim()
    const m = cleaned.match(CUT_RE)
    const zh = (m ? m[1] : cleaned).trim()
    if (zh) out.push([en, zh])
  }
  return out
}

function shuffle<T>(arr: T[]): T[] {
  const out = arr.slice()
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

export async function loadClickWords(level: 'CET-4' | 'CET-6'): Promise<Pair[]> {
  const key = level === 'CET-6' ? 'CET-6' : 'CET-4'
  if (_cache[key]) return _cache[key]
  const file = key === 'CET-6' ? 'words-cet6.txt' : 'words-cet4.txt'
  const res = await fetch(`/static/${file}`)
  if (!res.ok) throw new Error(`加载词库失败：${file}`)
  const words = shuffle(parseWordlist(await res.text()))
  _cache[key] = words
  return words
}
