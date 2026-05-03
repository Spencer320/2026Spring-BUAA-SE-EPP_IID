export const DR_STATUS_MAP = {
    pending: { label: '待处理', type: 'info' },
    queued: { label: '排队中', type: 'info' },
    running: { label: '执行中', type: 'warning' },
    completed: { label: '已完成', type: 'success' },
    failed: { label: '失败', type: 'danger' },
    aborted: { label: '用户中止', type: 'info' },
    admin_stopped: { label: '管理员中断', type: 'danger' },
    violation_pending: { label: '违规待处理', type: 'danger' },
    needs_review: { label: '待人工复核', type: 'warning' },
    archived: { label: '已归档', type: 'info' }
}

export const DR_PHASE_CONFIG = {
    planning: { label: '规划', color: '#409EFF' },
    searching: { label: '检索', color: '#67C23A' },
    reading: { label: '阅读', color: '#E6A23C' },
    reflecting: { label: '反思', color: '#909399' },
    writing: { label: '生成报告', color: '#F56C6C' }
}
