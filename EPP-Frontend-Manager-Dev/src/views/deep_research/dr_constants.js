/** 深度研究 AgentTask 状态与阶段（对齐 research_agent） */
export const DR_STATUS_MAP = {
    pending: { label: '待启动', type: 'info' },
    running: { label: '执行中', type: 'warning' },
    pending_action: { label: '待确认', type: 'warning' },
    completed: { label: '已完成', type: 'success' },
    failed: { label: '失败', type: 'danger' },
    cancelled: { label: '已取消', type: 'info' }
}

export const DR_PHASE_CONFIG = {
    plan: { label: '规划', color: '#409EFF' },
    decide: { label: '决策', color: '#606266' },
    search: { label: '检索', color: '#67C23A' },
    read: { label: '阅读', color: '#E6A23C' },
    reflect: { label: '反思', color: '#909399' },
    write: { label: '撰写', color: '#F56C6C' }
}

export const RA_STATUS_MAP = {
    pending: { label: '待启动', type: 'info' },
    running: { label: '执行中', type: 'warning' },
    pending_action: { label: '待确认', type: 'warning' },
    completed: { label: '已完成', type: 'success' },
    failed: { label: '失败', type: 'danger' },
    cancelled: { label: '已取消', type: 'info' }
}
