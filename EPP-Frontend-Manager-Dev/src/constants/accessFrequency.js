export const FEATURE_OPTIONS = [
    { value: 'deep_research', label: '深度研究', quotaMode: 'count', unit: '次' },
    { value: 'research_assistant', label: '科研助手', quotaMode: 'tokens', unit: 'Token' }
]

export const WINDOW_OPTIONS = [
    { value: 'daily', label: '每日' },
    { value: 'weekly', label: '每周' },
    { value: 'monthly', label: '每月' }
]

export function getFeatureMeta(feature) {
    return FEATURE_OPTIONS.find((o) => o.value === feature) || { label: feature, unit: '', quotaMode: 'count' }
}

export function quotaLimitLabel(feature) {
    const meta = getFeatureMeta(feature)
    return meta.quotaMode === 'tokens' ? 'Token 上限' : '次数上限'
}
