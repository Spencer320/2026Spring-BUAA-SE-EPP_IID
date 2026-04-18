import request from '@/utils/request.js'

export const getDeletedReportList = () => {
    return request({
        method: 'get',
        url: '/api/manage/filtered/comments',
        params: {}
    })
}

export const revertReport = (id, type) => {
    return request({
        method: 'post',
        url: `/api/manage/filtered/recover?id=${id}&type=${type}&direction=recover`,
        params: {}
    })
}

export const cancelRevertedReport = (id, type) => {
    return request({
        method: 'post',
        url: `/api/manage/filtered/recover?id=${id}&type=${type}&direction=revert`,
        params: {}
    })
}
