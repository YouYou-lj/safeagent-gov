export function readNumber(source: Record<string, unknown> | null | undefined, key: string): number {
  const value = source?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

export function readString(source: Record<string, unknown> | null | undefined, key: string): string {
  const value = source?.[key]
  return typeof value === 'string' ? value : ''
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}
