<template>
  <div
    v-if="loading || visibleItems.length"
    class="user-quota-bar"
    :class="{ compact, 'is-loading': loading }"
    v-loading="loading"
    element-loading-spinner="el-icon-loading"
    element-loading-background="transparent"
  >
    <span v-if="loading && !visibleItems.length" class="user-quota-chip is-loading-text">配额加载中…</span>
    <el-tooltip
      v-for="item in visibleItems"
      :key="item.feature"
      placement="bottom"
      :content="tooltipFor(item)"
    >
      <span :class="['user-quota-chip', chipClass(item)]">
        <span class="user-quota-chip-label">{{ item.feature_label }}</span>
        <span class="user-quota-chip-value">{{ summaryFor(item) }}</span>
      </span>
    </el-tooltip>
    <el-button
      v-if="showRefresh"
      type="text"
      class="user-quota-refresh"
      icon="el-icon-refresh"
      :loading="loading"
      @click="load"
    />
  </div>
</template>

<script>
import { getMyQuota } from '@/views/ResearchAgent/researchAgentApi.js'

const WINDOW_SHORT = {
  daily: '今日',
  weekly: '本周',
  monthly: '本月'
}

export default {
  name: 'UserAccessQuotaBar',
  props: {
    /** 仅展示指定 feature，如 ['research_assistant']；默认展示全部 */
    features: {
      type: Array,
      default: () => null
    },
    compact: {
      type: Boolean,
      default: false
    },
    showRefresh: {
      type: Boolean,
      default: true
    },
    autoLoad: {
      type: Boolean,
      default: true
    }
  },
  data () {
    return {
      loading: false,
      items: []
    }
  },
  computed: {
    visibleItems () {
      if (!this.items.length) return []
      if (!this.features || !this.features.length) return this.items
      const allow = new Set(this.features)
      return this.items.filter((x) => allow.has(x.feature))
    }
  },
  created () {
    if (this.autoLoad) this.load()
  },
  methods: {
    async load () {
      this.loading = true
      try {
        const res = await getMyQuota()
        this.items = (res.data && res.data.features) || []
      } catch (e) {
        this.items = []
      } finally {
        this.loading = false
      }
    },
    windowShort (window) {
      return WINDOW_SHORT[window] || '本周期'
    },
    formatNumber (n) {
      const v = Number(n)
      if (!Number.isFinite(v)) return '0'
      return v.toLocaleString('zh-CN')
    },
    summaryFor (item) {
      const win = this.windowShort(item.window)
      if (item.banned) return `${win} · 已禁用`
      if (item.unlimited) return `${win} · 不限`
      if (item.quota_unit === 'tokens') {
        const rem = item.remaining
        if (rem == null) return `${win} · 不限`
        return `${win}剩余 ${this.formatNumber(rem)} Token`
      }
      const rem = item.remaining
      if (rem == null) return `${win} · 不限`
      return `${win}剩余 ${rem} 次`
    },
    tooltipFor (item) {
      const win = this.windowShort(item.window)
      if (item.banned) return `${item.feature_label}：已被管理员禁用`
      if (item.unlimited) return `${item.feature_label}：${win}不限制使用`
      const unit = item.quota_unit === 'tokens' ? 'Token' : '次'
      const used = item.quota_unit === 'tokens' ? this.formatNumber(item.used) : item.used
      const limit = item.quota_unit === 'tokens' ? this.formatNumber(item.limit) : item.limit
      const rem = item.remaining == null ? '不限' : (item.quota_unit === 'tokens' ? this.formatNumber(item.remaining) : item.remaining)
      return `${item.feature_label}（${win}）\n已用：${used} ${unit}\n上限：${limit} ${unit}\n剩余：${rem} ${unit}`
    },
    chipClass (item) {
      if (item.banned) return 'is-banned'
      if (item.unlimited) return 'is-unlimited'
      if (item.remaining != null && item.remaining <= 0) return 'is-empty'
      if (item.limit > 0 && item.remaining != null && item.remaining / item.limit < 0.15) {
        return 'is-low'
      }
      return ''
    }
  }
}
</script>

<style scoped>
.user-quota-bar {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  max-width: 100%;
}
.user-quota-bar.compact .user-quota-chip {
  font-size: 11px;
  padding: 2px 8px;
}
.user-quota-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.3;
  background: #f4f6fb;
  border: 1px solid #e4e9f2;
  color: #4a5568;
  cursor: default;
}
.user-quota-chip-label {
  color: #606266;
  font-weight: 500;
}
.user-quota-chip-value {
  color: #303133;
}
.user-quota-chip.is-low {
  background: #fdf6ec;
  border-color: #f5dab1;
  color: #b88230;
}
.user-quota-chip.is-low .user-quota-chip-value {
  color: #e6a23c;
}
.user-quota-chip.is-empty,
.user-quota-chip.is-banned {
  background: #fef0f0;
  border-color: #fbc4c4;
  color: #c45656;
}
.user-quota-chip.is-unlimited {
  background: #f0f9eb;
  border-color: #c2e7b0;
  color: #529b2e;
}
.user-quota-refresh {
  padding: 0 4px;
  min-height: auto;
  color: #909399;
}
.user-quota-chip.is-loading-text {
  color: #909399;
  background: #fafafa;
}
</style>
