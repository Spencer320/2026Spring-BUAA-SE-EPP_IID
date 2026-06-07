const pad = value => String(value).padStart(2, '0')

const parseDateValue = value => {
  if (value instanceof Date) return { date: value, dateOnly: false }
  if (typeof value === 'number') return { date: new Date(value), dateOnly: false }
  if (typeof value !== 'string') return { date: new Date(value), dateOnly: false }

  const text = value.trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return { date: null, dateOnly: text }
  }

  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(text)
    ? text.replace(' ', 'T')
    : text
  return { date: new Date(normalized), dateOnly: false }
}

export const formatDateTime = (value, emptyText = '—') => {
  if (!value) return emptyText
  const parsed = parseDateValue(value)
  if (parsed.dateOnly) return parsed.dateOnly
  const date = parsed.date
  if (!date || Number.isNaN(date.getTime())) return String(value)

  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate())
  ].join('-') + ' ' + [
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds())
  ].join(':')
}

export const formatDate = (value, emptyText = '—') => {
  if (!value) return emptyText
  const parsed = parseDateValue(value)
  if (parsed.dateOnly) return parsed.dateOnly
  const date = parsed.date
  if (!date || Number.isNaN(date.getTime())) return String(value)

  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate())
  ].join('-')
}

export const formatTime = (value, emptyText = '—') => {
  if (!value) return emptyText
  const parsed = parseDateValue(value)
  const date = parsed.date
  if (!date || Number.isNaN(date.getTime())) return String(value)

  return [
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds())
  ].join(':')
}
