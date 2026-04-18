import request from '@/utils/request.js'

// ── 规则管理 ──────────────────────────────────────────────────────────────────

export const getRuleList = () =>
    request({ method: 'get', url: '/api/manage/access-frequency/rules' })

export const createRule = (data) =>
    request({ method: 'post', url: '/api/manage/access-frequency/rules', data })

export const updateRule = (ruleId, data) =>
    request({ method: 'put', url: `/api/manage/access-frequency/rules/${ruleId}`, data })

export const deleteRule = (ruleId) =>
    request({ method: 'delete', url: `/api/manage/access-frequency/rules/${ruleId}` })

// ── 用户配额覆盖管理 ──────────────────────────────────────────────────────────

export const getOverrideList = (params) =>
    request({ method: 'get', url: '/api/manage/access-frequency/user-overrides', params })

export const upsertOverride = (data) =>
    request({ method: 'post', url: '/api/manage/access-frequency/user-overrides', data })

export const deleteOverride = (overrideId) =>
    request({ method: 'delete', url: `/api/manage/access-frequency/user-overrides/${overrideId}` })

// ── 访问频次统计查询 ──────────────────────────────────────────────────────────

export const getGlobalStats = () =>
    request({ method: 'get', url: '/api/manage/access-frequency/stats' })

export const getUserStatsRanking = (params) =>
    request({ method: 'get', url: '/api/manage/access-frequency/stats/users', params })

export const getUserStatsDetail = (userId) =>
    request({ method: 'get', url: `/api/manage/access-frequency/stats/users/${userId}` })
