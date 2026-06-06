export const formatDateTime = (value) => {
    if (!value) return '—'
    if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value.trim())) {
        return value.trim()
    }
    const normalized =
        typeof value === 'string' && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(value.trim())
            ? value.trim().replace(' ', 'T')
            : value
    const date = new Date(normalized)
    if (Number.isNaN(date.getTime())) return String(value)
    const pad = (v) => String(v).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
        date.getMinutes()
    )}:${pad(date.getSeconds())}`
}

export const getApiErrorMessage = (error, fallback = '操作失败') => {
    return (
        error?.response?.data?.message ||
        error?.response?.data?.error ||
        error?.response?.data?.detail ||
        error?.message ||
        fallback
    )
}
