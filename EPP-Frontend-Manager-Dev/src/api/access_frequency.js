import request from '@/utils/request.js'

// ── 规则管理 ──────────────────────────────────────────────────────────────────

export const getRuleList = () => request({ method: 'get', url: '/api/manage/access-frequency/rules' })

export const createRule = (data) => request({ method: 'post', url: '/api/manage/access-frequency/rules', data })

export const updateRule = (ruleId, data) =>
    request({ method: 'put', url: `/api/manage/access-frequency/rules/${ruleId}`, data })

export const deleteRule = (ruleId) => request({ method: 'delete', url: `/api/manage/access-frequency/rules/${ruleId}` })

// ── 用户配额覆盖管理 ──────────────────────────────────────────────────────────

export const getOverrideList = (params) =>
    request({ method: 'get', url: '/api/manage/access-frequency/user-overrides', params })

export const upsertOverride = (data) =>
    request({ method: 'post', url: '/api/manage/access-frequency/user-overrides', data })

export const deleteOverride = (overrideId) =>
    request({ method: 'delete', url: `/api/manage/access-frequency/user-overrides/${overrideId}` })

// ── 访问频次统计查询 ──────────────────────────────────────────────────────────

export const getGlobalStats = () => request({ method: 'get', url: '/api/manage/access-frequency/stats' })

export const getUserStatsRanking = (params) =>
    request({ method: 'get', url: '/api/manage/access-frequency/stats/users', params })

export const getUserStatsDetail = (userId) =>
    request({ method: 'get', url: `/api/manage/access-frequency/stats/users/${userId}` })

// ── 并发限制管理 ──────────────────────────────────────────────────────────────

export const getConcurrencyRuleList = () =>
    request({ method: 'get', url: '/api/manage/access-frequency/concurrency-rules' })

export const createConcurrencyRule = (data) =>
    request({ method: 'post', url: '/api/manage/access-frequency/concurrency-rules', data })

export const updateConcurrencyRule = (ruleId, data) =>
    request({ method: 'put', url: `/api/manage/access-frequency/concurrency-rules/${ruleId}`, data })

export const deleteConcurrencyRule = (ruleId) =>
    request({ method: 'delete', url: `/api/manage/access-frequency/concurrency-rules/${ruleId}` })

export const getConcurrencyOverrideList = (params) =>
    request({ method: 'get', url: '/api/manage/access-frequency/concurrency-overrides', params })

export const upsertConcurrencyOverride = (data) =>
    request({ method: 'post', url: '/api/manage/access-frequency/concurrency-overrides', data })

export const deleteConcurrencyOverride = (overrideId) =>
    request({ method: 'delete', url: `/api/manage/access-frequency/concurrency-overrides/${overrideId}` })

export const getConcurrencyStats = (params) =>
    request({ method: 'get', url: '/api/manage/access-frequency/concurrency-stats', params })
