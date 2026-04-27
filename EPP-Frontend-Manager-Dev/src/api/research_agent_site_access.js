import request from '@/utils/request.js'

const PREFIX = '/api/research-agent/manage/site-access'

export const getSiteAccessPolicy = () =>
    request({
        method: 'get',
        url: `${PREFIX}/policy/`
    })

export const updateSiteAccessPolicy = (data) =>
    request({
        method: 'put',
        url: `${PREFIX}/policy/`,
        data
    })

export const getSiteAccessRules = (params) =>
    request({
        method: 'get',
        url: `${PREFIX}/rules/`,
        params
    })

export const createSiteAccessRule = (data) =>
    request({
        method: 'post',
        url: `${PREFIX}/rules/`,
        data
    })

export const updateSiteAccessRule = (ruleId, data) =>
    request({
        method: 'put',
        url: `${PREFIX}/rules/${ruleId}/`,
        data
    })

export const deleteSiteAccessRule = (ruleId) =>
    request({
        method: 'delete',
        url: `${PREFIX}/rules/${ruleId}/`
    })

export const getSiteAccessEvents = (params) =>
    request({
        method: 'get',
        url: `${PREFIX}/events/`,
        params
    })

export const getSiteAccessStats = () =>
    request({
        method: 'get',
        url: `${PREFIX}/stats/`
    })
