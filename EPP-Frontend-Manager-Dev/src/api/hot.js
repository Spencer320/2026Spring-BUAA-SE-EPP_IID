import request from '@/utils/request.js'

export const getHotPapers = () => {
    return request({
        method: 'get',
        url: '/api/manage/popular/papers',
        params: {}
    })
}

export const getHotKeywords = () => {
    return request({
        method: 'get',
        url: '/api/manage/popular/search',
        params: {}
    })
}

export const getVisitTime = () => {
    return request({
        method: 'get',
        url: '/api/manage/visittime',
        params: {}
    })
}
