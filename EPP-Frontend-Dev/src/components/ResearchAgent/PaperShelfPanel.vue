<template>
  <div class="ps-panel">
    <p class="ps-intro">
      <slot name="intro">
        文献列表为账号级共享，所有会话共用。检索结果需确认后才会加入；工作区文件可手动加入。点击条目标题可预览。
      </slot>
    </p>

    <div v-if="showBatchActions && items.length && selectable" class="ps-batch-bar">
      <el-button size="mini" plain @click="selectAllItems">全选</el-button>
      <el-button size="mini" plain @click="clearSelected">取消全选</el-button>
      <el-button size="mini" type="danger" plain :loading="removingAll" @click="removeAllItems">全部移除</el-button>
    </div>

    <div v-if="pendingCitations.length" class="ps-pending">
      <div class="ps-pending-hd">
        <span>检索结果待加入（{{ pendingCitations.length }}）</span>
        <el-button type="primary" size="mini" plain :loading="addingBatch" @click="addAllPending">
          全部加入展示区
        </el-button>
      </div>
      <div class="ps-pending-list">
        <div v-for="(c, idx) in pendingCitations" :key="pendingKey(c, idx)" class="ps-pending-row">
          <div class="ps-pending-main">
            <div class="ps-pending-title">{{ c.title || '(无标题)' }}</div>
            <div v-if="c.url" class="ps-pending-url">{{ truncate(c.url, 80) }}</div>
          </div>
          <el-button size="mini" type="text" :loading="addingOneKey === pendingKey(c, idx)" @click="addOnePending(c, idx)">
            加入
          </el-button>
        </div>
      </div>
    </div>

    <div v-loading="loading" class="ps-list">
      <el-empty v-if="!items.length && !loading" description="展示区暂无条目" :image-size="64" />
      <el-checkbox-group v-if="selectable" v-model="selectedIds" class="ps-group" @change="onSelectionChange">
        <div v-for="it in items" :key="it.id" class="ps-row">
          <el-checkbox :label="it.id" class="ps-cb">&nbsp;</el-checkbox>
          <div class="ps-main" title="点击预览" @click="$emit('preview', it)">
            <div class="ps-title">
              {{ it.title }}
              <el-tag size="mini" effect="plain">{{ tierLabel(it.context_tier) }}</el-tag>
              <el-tag v-if="it.source_kind === 'workspace_file'" size="mini" type="success" effect="plain">工作区</el-tag>
              <el-tag v-else size="mini" type="warning" effect="plain">外链</el-tag>
            </div>
            <div v-if="it.abstract" class="ps-abs">{{ truncate(it.abstract, 160) }}</div>
            <div class="ps-actions">
              <el-button v-if="it.primary_url || it.external_jump_url" type="text" size="mini" @click.stop="openExternal(it)">打开链接</el-button>
              <el-button type="text" size="mini" class="ps-danger" @click.stop="removeItem(it)">移除</el-button>
            </div>
          </div>
        </div>
      </el-checkbox-group>
      <div v-else class="ps-group">
        <div v-for="it in items" :key="it.id" class="ps-row">
          <div class="ps-main ps-main-full" title="点击预览" @click="$emit('preview', it)">
            <div class="ps-title">
              {{ it.title }}
              <el-tag size="mini" effect="plain">{{ tierLabel(it.context_tier) }}</el-tag>
              <el-tag v-if="it.source_kind === 'workspace_file'" size="mini" type="success" effect="plain">工作区</el-tag>
              <el-tag v-else size="mini" type="warning" effect="plain">外链</el-tag>
            </div>
            <div v-if="it.abstract" class="ps-abs">{{ truncate(it.abstract, 160) }}</div>
            <div class="ps-actions">
              <el-button v-if="it.primary_url || it.external_jump_url" type="text" size="mini" @click.stop="openExternal(it)">打开链接</el-button>
              <el-button type="text" size="mini" class="ps-danger" @click.stop="removeItem(it)">移除</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="$slots.footer" class="ps-footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<script>
import {
  listPaperShelf,
  addPaperShelfExternal,
  deletePaperShelfItem
} from '@/views/ResearchAgent/researchAgentApi.js'

export default {
  name: 'PaperShelfPanel',
  props: {
    selectable: { type: Boolean, default: true },
    showBatchActions: { type: Boolean, default: true },
    pendingCitations: { type: Array, default: () => [] },
    sessionId: { type: String, default: '' },
    inputLocked: { type: Boolean, default: false },
    refreshToken: { type: [Number, String], default: 0 }
  },
  data () {
    return {
      items: [],
      loading: false,
      selectedIds: [],
      pendingSelectedIds: null,
      addingBatch: false,
      addingOneKey: '',
      removingAll: false
    }
  },
  watch: {
    refreshToken () {
      this.load()
    }
  },
  mounted () {
    this.load()
  },
  methods: {
    getSelectedIds () {
      return [...this.selectedIds]
    },
    setSelectedIds (ids) {
      this.pendingSelectedIds = Array.isArray(ids) ? ids.slice() : []
      this.syncSelectedFromPending()
    },
    syncSelectedFromPending () {
      if (this.pendingSelectedIds == null) return
      const pending = this.pendingSelectedIds
      if (!pending.length) {
        this.selectedIds = []
        this.pendingSelectedIds = null
        this.onSelectionChange(this.selectedIds)
        return
      }
      const valid = new Set((this.items || []).map(x => String(x.id)))
      const next = pending.filter(id => valid.has(String(id)))
      if (!next.length && this.loading) return
      this.selectedIds = next
      this.pendingSelectedIds = null
      this.onSelectionChange(this.selectedIds)
    },
    truncate (s, n) {
      const t = String(s || '')
      return t.length > n ? t.slice(0, n) + '…' : t
    },
    tierLabel (tier) {
      const map = {
        abstract_only: '摘要',
        link_only: '链接',
        full_text_available: '全文',
        workspace_opaque: '工作区'
      }
      return map[tier] || tier || '—'
    },
    pendingKey (c, idx) {
      return `${(c.url || '').trim()}|${c.title || ''}|${idx}`
    },
    onSelectionChange (val) {
      this.$emit('selection-change', val)
    },
    openExternal (it) {
      const u = it.external_jump_url || it.primary_url
      if (u) window.open(u, '_blank', 'noopener,noreferrer')
    },
    pruneSelection () {
      const ids = new Set(this.items.map(x => x.id))
      this.selectedIds = this.selectedIds.filter(id => ids.has(id))
    },
    selectAllItems () {
      this.selectedIds = this.items.map(x => x.id)
      this.onSelectionChange(this.selectedIds)
    },
    clearSelected () {
      this.selectedIds = []
      this.onSelectionChange(this.selectedIds)
    },
    async removeAllItems () {
      if (!this.items.length) return
      try {
        await this.$confirm('确定从展示区移除全部条目？', '确认', { type: 'warning' })
      } catch (e) {
        return
      }
      this.removingAll = true
      const ids = this.items.map(x => x.id)
      let ok = 0
      for (const id of ids) {
        try {
          await deletePaperShelfItem(id)
          ok += 1
        } catch (e) {
          /* continue */
        }
      }
      this.selectedIds = []
      this.onSelectionChange(this.selectedIds)
      await this.load()
      this.$message.success(ok ? `已移除 ${ok} 条` : '移除失败')
      this.removingAll = false
    },
    async load () {
      this.loading = true
      try {
        const res = await listPaperShelf()
        this.items = res.data.items || []
        this.pruneSelection()
        this.$emit('loaded', this.items)
      } catch (e) {
        this.items = []
        this.$emit('error', e)
      } finally {
        this.loading = false
        this.syncSelectedFromPending()
      }
    },
    async removeItem (it) {
      if (!it.id) return
      try {
        await this.$confirm('从展示区移除此条目？', '确认', { type: 'warning' })
      } catch (e) {
        return
      }
      try {
        await deletePaperShelfItem(it.id)
        if (this.selectedIds.includes(it.id)) {
          this.selectedIds = this.selectedIds.filter(x => x !== it.id)
        }
        this.$emit('removed', it)
        await this.load()
      } catch (e) {
        this.$message.error(this.apiError(e, '删除失败'))
      }
    },
    async addOnePending (c, idx) {
      const key = this.pendingKey(c, idx)
      this.addingOneKey = key
      try {
        await addPaperShelfExternal({
          citations: [c],
          search_query: c.search_query || ''
        })
        this.$message.success('已加入展示区')
        await this.load()
        this.$emit('pending-added')
      } catch (e) {
        this.$message.error(this.apiError(e, '加入失败'))
      } finally {
        this.addingOneKey = ''
      }
    },
    async addAllPending () {
      if (!this.pendingCitations.length) return
      this.addingBatch = true
      try {
        const res = await addPaperShelfExternal({
          citations: this.pendingCitations,
          search_query: (this.pendingCitations[0] && this.pendingCitations[0].search_query) || ''
        })
        const created = res.data.created || 0
        this.$message.success(created ? `已加入 ${created} 条` : '条目均已存在，未新增')
        await this.load()
        this.$emit('pending-added')
      } catch (e) {
        this.$message.error(this.apiError(e, '批量加入失败'))
      } finally {
        this.addingBatch = false
      }
    },
    apiError (e, fallback) {
      const data = e && e.response && e.response.data
      const msg = (data && (data.message || data.error)) || (e && e.message)
      return msg || fallback
    }
  }
}
</script>

<style scoped>
.ps-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}
.ps-intro {
  font-size: 12px;
  line-height: 1.55;
  color: #6b7c93;
  margin: 0 0 10px;
}
.ps-batch-bar {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.ps-pending {
  flex-shrink: 0;
  margin-bottom: 12px;
  padding: 10px;
  border-radius: 8px;
  border: 1px dashed #c6d9f5;
  background: #f5f9ff;
}
.ps-pending-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #1a2b4a;
  margin-bottom: 8px;
}
.ps-pending-list {
  max-height: 160px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ps-pending-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: #fff;
  border: 1px solid #e8eef5;
}
.ps-pending-main {
  flex: 1;
  min-width: 0;
}
.ps-pending-title {
  font-size: 12px;
  font-weight: 500;
  color: #303133;
}
.ps-pending-url {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
  word-break: break-all;
}
.ps-list {
  flex: 1;
  min-height: 80px;
  overflow-y: auto;
}
.ps-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}
.ps-row {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid #edf2f7;
  background: #fbfdff;
}
.ps-cb {
  margin-top: 2px;
}
.ps-main {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}
.ps-main-full {
  width: 100%;
}
.ps-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.ps-abs {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.45;
}
.ps-actions {
  margin-top: 8px;
  display: flex;
  gap: 4px;
}
.ps-danger {
  color: #f56c6c;
}
.ps-footer {
  flex-shrink: 0;
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid #e8eef5;
}
.ps-muted {
  font-size: 12px;
  color: #909399;
  margin: 8px 0 0;
}
</style>
