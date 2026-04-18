# 管理端前端设计文档
## 访问频次控制 & Deep Research 任务实时监控

> **项目**：EPP-Frontend-Manager-Dev（学术科研助手管理端）  
> **功能归属**：管理端新增模块  
> **开发周期**：第一迭代周  
> **依据文档**：`管理端-访问频次控制与DR监控-概要设计.md`、`Deep-Research-概要设计.md`  
> **文档版本**：v0.1 | 编写日期：2026-04-18

---

## 目录

1. [现有项目结构概览](#1-现有项目结构概览)
2. [总体修改规划](#2-总体修改规划)
3. [功能一：访问频次控制](#3-功能一访问频次控制)
   - [3.1 页面层级结构](#31-页面层级结构)
   - [3.2 路由设计](#32-路由设计)
   - [3.3 API 模块设计](#33-api-模块设计)
   - [3.4 视图组件设计](#34-视图组件设计)
4. [功能二：Deep Research 任务实时监控](#4-功能二deep-research-任务实时监控)
   - [4.1 页面层级结构](#41-页面层级结构)
   - [4.2 路由设计](#42-路由设计)
   - [4.3 API 模块设计](#43-api-模块设计)
   - [4.4 视图组件设计](#44-视图组件设计)
5. [侧边栏修改](#5-侧边栏修改)
6. [新增文件清单](#6-新增文件清单)
7. [现有文件修改清单](#7-现有文件修改清单)
8. [开发子任务拆分](#8-开发子任务拆分)

---

## 1. 现有项目结构概览

```
EPP-Frontend-Manager-Dev/
├── src/
│   ├── api/                  # 按模块拆分的 API 请求函数
│   │   ├── server.js         # 服务器状态
│   │   ├── manager.js        # 管理员登录/登出
│   │   ├── user.js           # 用户管理
│   │   ├── paper.js          # 论文管理
│   │   ├── hot.js            # 热门数据
│   │   ├── report.js         # 用户举报审核
│   │   └── system_report.js  # 评论管理
│   ├── router/
│   │   └── index.js          # 路由表 + 守卫
│   ├── store/
│   │   └── index.js          # Vuex store
│   ├── utils/
│   │   └── request.js        # Axios 封装实例
│   └── views/
│       ├── layout/
│       │   └── LayoutContainer.vue   # 整体布局（侧边栏 + 顶栏）
│       ├── main/         # 首页
│       ├── user/         # 用户管理
│       ├── paper/        # 论文管理
│       ├── hot/          # 热门数据
│       ├── report/       # 用户举报审核
│       └── system_report/# 评论管理
```

**技术栈**：Vue 3（Options API）、Vue Router 4、Vuex 4、Element Plus、ECharts、Axios、Sass

**代码风格约定**（与现有代码保持一致）：
- 组件使用 Options API（`data/computed/methods/created/mounted`）
- API 函数使用 `export const xxx = () => request({...})` 形式
- 路由使用懒加载 `() => import(...)`
- 布局使用 Element Plus 的 `el-collapse + el-menu + el-table` 模式
- 子页面间导航使用横向 `el-menu` + `router-view`

---

## 2. 总体修改规划

### 2.1 新增内容汇总

| 类型 | 数量 | 说明 |
|------|------|------|
| 新增 API 文件 | 2 | `src/api/access_frequency.js`、`src/api/deep_research.js` |
| 新增视图目录 | 2 | `src/views/access_frequency/`、`src/views/deep_research/` |
| 新增视图组件 | 9 | 见各功能详细设计 |
| 修改路由文件 | 1 | `src/router/index.js` 新增 2 组路由 |
| 修改布局文件 | 1 | `src/views/layout/LayoutContainer.vue` 新增 2 个侧边栏菜单项 |

### 2.2 与现有模块的关系

- **无破坏性改动**：两个新功能完全新增，不修改任何现有视图组件逻辑
- **侧边栏扩展**：在现有 6 个菜单项后追加 2 个（访问频次控制、DR 监控）
- **activeMenu 修正**：现有 `activeMenu` 计算属性对 `/report` 前缀的高亮逻辑存在潜在冲突，本次修改时一并修复

---

## 3. 功能一：访问频次控制

### 3.1 页面层级结构

```
/access-frequency                      ← 重定向至 /access-frequency/rules
├── AccessFrequencyManage.vue          ← 布局容器（折叠标题 + 横向子菜单 + router-view）
│   ├── /access-frequency/rules        ← FrequencyRules.vue       规则管理
│   ├── /access-frequency/overrides    ← UserOverrides.vue        用户配额覆盖
│   └── /access-frequency/stats        ← FrequencyStats.vue       访问统计
```

**交互说明**：
- 整体采用与 `ReportManage.vue` 相同的折叠面板 + 横向子菜单模式
- 三个子页面通过顶部横向 `el-menu` 切换

### 3.2 路由设计

在 `src/router/index.js` 的 `LayoutContainer` 子路由中追加：

```js
{
    path: '/access-frequency',
    redirect: '/access-frequency/rules',
    component: () => import('@/views/access_frequency/AccessFrequencyManage.vue'),
    children: [
        {
            path: '/access-frequency/rules',
            component: () => import('@/views/access_frequency/FrequencyRules.vue')
        },
        {
            path: '/access-frequency/overrides',
            component: () => import('@/views/access_frequency/UserOverrides.vue')
        },
        {
            path: '/access-frequency/stats',
            component: () => import('@/views/access_frequency/FrequencyStats.vue')
        }
    ]
}
```

### 3.3 API 模块设计

新建 `src/api/access_frequency.js`：

```js
import request from '@/utils/request.js'

// ── 规则管理 ──────────────────────────────────────────

// 获取全部频次规则列表
export const getRuleList = () => request({ method: 'get', url: '/api/manage/access-frequency/rules' })

// 新增规则
// data: { feature, window, max_count, is_enabled, description }
export const createRule = (data) => request({ method: 'post', url: '/api/manage/access-frequency/rules', data })

// 修改规则（上限、窗口、启停、描述）
// data: { window?, max_count?, is_enabled?, description? }
export const updateRule = (ruleId, data) =>
    request({ method: 'put', url: `/api/manage/access-frequency/rules/${ruleId}`, data })

// 删除规则
export const deleteRule = (ruleId) =>
    request({ method: 'delete', url: `/api/manage/access-frequency/rules/${ruleId}` })

// ── 用户配额覆盖管理 ───────────────────────────────────

// 查看所有用户覆盖配置（params: { user_id?, feature? }）
export const getOverrideList = (params) =>
    request({ method: 'get', url: '/api/manage/access-frequency/user-overrides', params })

// 新增/更新用户配额覆盖
// data: { user_id, feature, max_count, reason }
export const upsertOverride = (data) =>
    request({ method: 'post', url: '/api/manage/access-frequency/user-overrides', data })

// 删除覆盖（恢复全局规则）
export const deleteOverride = (overrideId) =>
    request({ method: 'delete', url: `/api/manage/access-frequency/user-overrides/${overrideId}` })

// ── 访问频次统计查询 ────────────────────────────────────

// 全局统计（各功能今日/本周调用次数、被拒次数）
export const getGlobalStats = () => request({ method: 'get', url: '/api/manage/access-frequency/stats' })

// 用户维度排行 Top-N（params: { feature?, date?, top_n? }）
export const getUserStatsRanking = (params) =>
    request({ method: 'get', url: '/api/manage/access-frequency/stats/users', params })

// 特定用户访问频次详情
export const getUserStatsDetail = (userId) =>
    request({ method: 'get', url: `/api/manage/access-frequency/stats/users/${userId}` })
```

**字段说明**（`feature` 枚举值与后端一致）：

| 枚举值 | 显示文本 |
|--------|----------|
| `deep_research` | Deep Research 任务 |
| `ai_chat` | AI 对话（研读/调研助手）|
| `summary` | 综述报告生成 |
| `export` | 报告批量导出 |

### 3.4 视图组件设计

#### 3.4.1 `AccessFrequencyManage.vue`（主容器）

**职责**：折叠面板容器 + 横向子菜单导航 + `<router-view>`  
**参照**：与 `ReportManage.vue` 结构完全一致，替换标题和菜单项

```
AccessFrequencyManage.vue
├── el-collapse（标题：访问频次控制）
│   ├── el-menu（horizontal，router 模式）
│   │   ├── el-menu-item → /access-frequency/rules      「规则配置」
│   │   ├── el-menu-item → /access-frequency/overrides  「用户特殊配额」
│   │   └── el-menu-item → /access-frequency/stats      「访问统计」
│   └── router-view（渲染子页面）
```

**模板结构**（与 `ReportManage.vue` 保持风格一致）：
```html
<el-collapse v-model="isClsActive">
  <el-collapse-item name="1">
    <template #title>
      <div class="collapse-title">
        <el-icon><i-ep-Odometer /></el-icon>
        <span class="collapse-title-text">访问频次控制</span>
      </div>
    </template>
    <el-menu :default-active="$route.path" class="menu" mode="horizontal" :ellipsis="false" router>
      <el-menu-item index="/access-frequency/rules">规则配置</el-menu-item>
      <el-menu-item index="/access-frequency/overrides">用户特殊配额</el-menu-item>
      <el-menu-item index="/access-frequency/stats">访问统计</el-menu-item>
    </el-menu>
    <div style="padding: 10px"><router-view></router-view></div>
  </el-collapse-item>
</el-collapse>
```

---

#### 3.4.2 `FrequencyRules.vue`（规则配置）

**职责**：展示、新增、编辑、删除各功能的全局频次规则；支持一键启用/禁用规则

**页面布局**：

```
FrequencyRules.vue
├── 操作区（右侧对齐）
│   └── el-button「新增规则」→ 触发 新增 Dialog
├── el-table（规则列表）
│   ├── 列：功能名称（feature_label）
│   ├── 列：时间窗口（window：每日/每周/每月）
│   ├── 列：上限次数（max_count，-1 显示「不限制」）
│   ├── 列：状态（is_enabled → el-switch，即时 PUT 更新）
│   ├── 列：描述
│   ├── 列：最后更新时间（updated_at）
│   └── 列：操作（编辑按钮 / 删除按钮）
└── el-dialog「新增 / 编辑规则」
    ├── el-select：功能类型（feature）[新增时可选；编辑时禁用]
    ├── el-select：时间窗口（window）
    ├── el-input-number：上限次数（max_count，-1 表示不限制）
    ├── el-switch：是否启用
    └── el-input：备注说明（description）
```

**关键逻辑**：
- `created()` 调用 `getRuleList()` 初始化表格数据
- `el-switch` 的 `@change` 事件直接调用 `updateRule(ruleId, { is_enabled })` 实现即时切换
- 新增规则时，`feature` 下拉选项只显示当前**尚无规则**的功能（前端过滤已存在的 feature）
- 删除规则前使用 `ElMessageBox.confirm` 二次确认
- 编辑对话框通过 `currentRule` 数据属性传递选中行

**数据结构**：
```js
data() {
  return {
    rules: [],          // 规则列表
    isLoading: false,
    dialogVisible: false,
    isEditMode: false,  // true=编辑, false=新增
    formData: {
      rule_id: null,
      feature: '',
      window: 'daily',
      max_count: 10,
      is_enabled: true,
      description: ''
    },
    featureOptions: [
      { value: 'deep_research', label: 'Deep Research 任务' },
      { value: 'ai_chat',       label: 'AI 对话' },
      { value: 'summary',       label: '综述报告生成' },
      { value: 'export',        label: '报告批量导出' }
    ],
    windowOptions: [
      { value: 'daily',   label: '每日' },
      { value: 'weekly',  label: '每周' },
      { value: 'monthly', label: '每月' }
    ]
  }
}
```

---

#### 3.4.3 `UserOverrides.vue`（用户特殊配额）

**职责**：展示所有用户级配额覆盖，支持新增特殊配额（提额/封禁）和删除（恢复全局规则）

**页面布局**：

```
UserOverrides.vue
├── 筛选区
│   ├── el-input：按用户名/用户ID 筛选
│   ├── el-select：按功能类型筛选
│   └── el-button「搜索」/ 「新增特殊配额」
├── el-table（覆盖配置列表）
│   ├── 列：用户名
│   ├── 列：用户ID（隐藏/tooltip 显示）
│   ├── 列：功能类型
│   ├── 列：配额上限（max_count，-1 显示「无限制」，0 显示「完全封禁」）
│   ├── 列：备注原因（reason）
│   ├── 列：创建时间
│   └── 列：操作（删除按钮）
└── el-dialog「新增特殊配额」
    ├── el-input：用户名/用户ID（搜索后选择，或直接填写 user_id）
    ├── el-select：功能类型
    ├── el-input-number：特殊配额（max_count）
    │   └── 下方提示：-1=不限制, 0=完全封禁, >0=指定次数
    └── el-input：备注原因（reason）
```

**关键逻辑**：
- 配额上限显示逻辑：
  - `max_count === -1` → `<el-tag type="success">无限制</el-tag>`
  - `max_count === 0` → `<el-tag type="danger">完全封禁</el-tag>`
  - 其他 → 显示数字
- 删除前使用 `ElMessageBox.confirm` 二次确认（提示"删除后将恢复全局规则"）

---

#### 3.4.4 `FrequencyStats.vue`（访问统计）

**职责**：展示各功能的实时访问统计数据（数字卡片 + 排行表格）；支持查看特定用户的详情弹窗

**页面布局**：

```
FrequencyStats.vue
├── 概览数字卡片区（复用现有 number-box 样式）
│   ├── 卡片：今日总调用次数
│   ├── 卡片：今日被拒次数
│   ├── 卡片：启用规则数
│   └── （按功能分列：DR / AI对话 / 综述 / 导出）
├── 用户排行区
│   ├── 筛选区：el-select 筛选功能类型
│   ├── el-table（用户访问排行，Top-N）
│   │   ├── 列：排名
│   │   ├── 列：用户名
│   │   ├── 列：调用次数
│   │   ├── 列：被拒次数
│   │   └── 列：操作（「查看配额详情」→ 弹出用户详情 Dialog）
│   └── el-dialog「用户配额详情」
│       ├── 用户名/ID
│       └── el-table（各功能：配额上限/已用次数/剩余次数/是否用了覆盖配置）
└── 刷新按钮（手动刷新统计数据）
```

**关键逻辑**：
- `created()` 调用 `getGlobalStats()` 初始化统计卡片、调用 `getUserStatsRanking()` 初始化排行
- 「查看配额详情」调用 `getUserStatsDetail(userId)` 获取用户级详情并显示对话框
- `el-select` 的功能筛选变化时，重新调用 `getUserStatsRanking({ feature })` 刷新排行

---

## 4. 功能二：Deep Research 任务实时监控

### 4.1 页面层级结构

```
/deep-research                          ← 重定向至 /deep-research/tasks
├── DRMonitorManage.vue                 ← 布局容器（折叠标题 + 横向子菜单 + router-view）
│   ├── /deep-research/tasks            ← DRTaskList.vue       任务列表（含实时监控）
│   └── /deep-research/audit-logs       ← DRAuditLogs.vue      审计日志
│
│   [以下为对话框/抽屉组件，不走路由，由 DRTaskList 内部控制]
│   ├── DRTaskDetailDrawer.vue          ← 任务详情侧抽屉（含元信息 + 干预操作）
│   └── DRTraceDrawer.vue               ← 执行轨迹侧抽屉（步骤时间线）
```

**设计说明**：
- 任务详情和执行轨迹使用 `el-drawer` 而非 `el-dialog`，因为内容较长，侧边抽屉体验更好
- 统计概览数字卡片直接集成在 `DRTaskList.vue` 顶部，不单独新建页面

### 4.2 路由设计

在 `src/router/index.js` 的 `LayoutContainer` 子路由中追加：

```js
{
    path: '/deep-research',
    redirect: '/deep-research/tasks',
    component: () => import('@/views/deep_research/DRMonitorManage.vue'),
    children: [
        {
            path: '/deep-research/tasks',
            component: () => import('@/views/deep_research/DRTaskList.vue')
        },
        {
            path: '/deep-research/audit-logs',
            component: () => import('@/views/deep_research/DRAuditLogs.vue')
        }
    ]
}
```

### 4.3 API 模块设计

新建 `src/api/deep_research.js`：

```js
import request from '@/utils/request.js'

// ── 统计概览 ───────────────────────────────────────────

// 整体统计摘要（running_count / queued_count / today_total 等）
export const getDRStats = () => request({ method: 'get', url: '/api/manage/deep-research/stats' })

// ── 任务列表 ───────────────────────────────────────────

/**
 * 分页任务列表（支持多条件筛选）
 * params: {
 *   status?:    string,   // 逗号分隔多状态，如 "running,queued"
 *   user_id?:  string,
 *   date_from?: string,   // ISO 8601
 *   date_to?:  string,
 *   page_num?: number,
 *   page_size?: number
 * }
 */
export const getDRTaskList = (params) =>
    request({ method: 'get', url: '/api/manage/deep-research/tasks', params })

// ── 任务详情与执行轨迹 ──────────────────────────────────

// 任务完整详情（含报告元信息）
export const getDRTaskDetail = (taskId) =>
    request({ method: 'get', url: `/api/manage/deep-research/tasks/${taskId}` })

// 执行轨迹（步骤列表）
export const getDRTaskTrace = (taskId) =>
    request({ method: 'get', url: `/api/manage/deep-research/tasks/${taskId}/trace` })

// ── 管理干预操作 ───────────────────────────────────────

// 强制中断任务
// data: { reason: string }
export const forceSTopTask = (taskId, data) =>
    request({ method: 'post', url: `/api/manage/deep-research/tasks/${taskId}/force-stop`, data })

// 屏蔽任务报告输出
// data: { reason: string }
export const suppressOutput = (taskId, data) =>
    request({ method: 'post', url: `/api/manage/deep-research/tasks/${taskId}/suppress-output`, data })

// 恢复任务报告输出
// data: { reason?: string }
export const unsuppressOutput = (taskId, data) =>
    request({ method: 'post', url: `/api/manage/deep-research/tasks/${taskId}/unsuppress-output`, data })

// ── 审计日志 ───────────────────────────────────────────

// 指定任务的审计日志
export const getTaskAuditLogs = (taskId) =>
    request({ method: 'get', url: `/api/manage/deep-research/tasks/${taskId}/audit-logs` })

// 全局审计日志列表（params: { admin?, action?, date_from?, date_to? }）
export const getGlobalAuditLogs = (params) =>
    request({ method: 'get', url: '/api/manage/deep-research/audit-logs', params })
```

### 4.4 视图组件设计

#### 4.4.1 `DRMonitorManage.vue`（主容器）

**职责**：折叠面板容器 + 横向子菜单导航 + `<router-view>`  
**参照**：与 `ReportManage.vue` / `AccessFrequencyManage.vue` 结构保持一致

```html
<el-collapse v-model="isClsActive">
  <el-collapse-item name="1">
    <template #title>
      <div class="collapse-title">
        <el-icon><i-ep-Monitor /></el-icon>
        <span class="collapse-title-text">Deep Research 监控</span>
      </div>
    </template>
    <el-menu :default-active="$route.path" class="menu" mode="horizontal" :ellipsis="false" router>
      <el-menu-item index="/deep-research/tasks">任务监控</el-menu-item>
      <el-menu-item index="/deep-research/audit-logs">审计日志</el-menu-item>
    </el-menu>
    <div style="padding: 10px"><router-view></router-view></div>
  </el-collapse-item>
</el-collapse>
```

---

#### 4.4.2 `DRTaskList.vue`（任务监控主页）

**职责**：
1. 顶部展示实时统计概览（数字卡片）
2. 中部提供多维筛选条件
3. 主体任务列表表格（支持分页）
4. 对运行中/排队中任务提供强制中断按钮
5. 对已完成任务提供屏蔽/恢复输出按钮
6. 查看任务详情（侧抽屉）/ 查看执行轨迹（侧抽屉）

**页面布局**：

```
DRTaskList.vue
├── 统计概览区（number-box 样式，复用现有样式）
│   ├── 卡片：运行中任务数（running_count）[高亮橙色]
│   ├── 卡片：排队中任务数（queued_count）
│   ├── 卡片：今日任务总数（today_total）
│   ├── 卡片：今日已完成（today_completed）
│   ├── 卡片：今日 Token 消耗（today_token_total，格式化为 xx.xx万）
│   └── 卡片：已屏蔽报告数（suppressed_count）[警示红色]
│
├── 筛选区
│   ├── el-select（多选）：任务状态筛选
│   │   选项：全部 / 运行中 / 排队中 / 已完成 / 失败 / 管理员中断 / 用户中止 / 合规审核中
│   ├── el-input：用户名/用户ID 搜索
│   ├── el-date-picker（range）：创建时间范围
│   ├── el-button「搜索」
│   ├── el-button「重置」
│   └── el-button「自动刷新」（el-switch 控制，开启后每5s自动重新请求）
│
├── el-table（任务列表）
│   ├── 列：任务ID（el-tooltip 显示全 UUID，表格显示截断版本）
│   ├── 列：用户名（可点击→筛选该用户任务）
│   ├── 列：研究问题 query（el-tooltip 显示全文）
│   ├── 列：状态（status → el-tag 颜色区分）
│   │   ├── running       → warning（黄色）
│   │   ├── queued        → info（蓝色）
│   │   ├── completed     → success（绿色）
│   │   ├── failed        → danger（红色）
│   │   ├── admin_stopped → danger（红色，「管理员中断」）
│   │   ├── aborted       → info（「用户中止」）
│   │   └── 其他          → info
│   ├── 列：当前阶段（current_phase，仅 running 状态显示，el-tag）
│   ├── 列：进度（progress，el-progress 进度条，仅 running 显示）
│   ├── 列：Token 消耗（token_used_total，格式化显示）
│   ├── 列：输出状态（output_suppressed → el-tag：正常/已屏蔽）
│   ├── 列：创建时间（created_at）
│   └── 列：操作
│       ├── 「详情」按钮 → 打开 DRTaskDetailDrawer
│       ├── 「轨迹」按钮 → 打开 DRTraceDrawer
│       ├── 「强制中断」按钮（仅 running/queued 显示）→ 确认后调用 forceStopTask
│       ├── 「屏蔽输出」按钮（completed + !output_suppressed 显示）
│       └── 「恢复输出」按钮（completed + output_suppressed 显示）
│
├── el-pagination
│   └── 分页（layout="total, sizes, prev, pager, next, jumper"）
│
├── DRTaskDetailDrawer（el-drawer，size="40%"）
│   └── 见 4.4.3
│
└── DRTraceDrawer（el-drawer，size="45%"）
    └── 见 4.4.4
```

**实时轮询设计**：

```
自动刷新逻辑：
├── data.autoRefresh: false  ← el-switch 绑定
├── data.refreshTimer: null  ← setInterval 句柄
├── watch.autoRefresh(val):
│   ├── val=true  → refreshTimer = setInterval(fetchData, 5000)
│   └── val=false → clearInterval(refreshTimer)
└── beforeUnmount() → clearInterval(refreshTimer)（防内存泄漏）
```

**强制中断操作流程**：

```
点击「强制中断」
    ↓
ElMessageBox.prompt('请填写中断原因', '强制中断确认', { inputPattern: /.+/, ... })
    ↓
调用 forceStopTask(taskId, { reason })
    ↓
成功 → ElMessage.success('中断指令已发送，任务将在下一轮检查后停止')
      → 刷新任务列表
失败 → ElMessage.error(error.response.data.message)
```

**屏蔽/恢复输出流程**：

```
点击「屏蔽输出」
    ↓
ElMessageBox.prompt('请填写屏蔽原因', '屏蔽报告输出', ...)
    ↓
调用 suppressOutput(taskId, { reason })
    ↓
成功 → ElMessage.success('报告已屏蔽') → 刷新列表
```

**数据结构**：

```js
data() {
  return {
    // 统计数据
    stats: {
      running_count: 0,
      queued_count: 0,
      today_total: 0,
      today_completed: 0,
      today_failed: 0,
      today_admin_stopped: 0,
      today_token_total: 0,
      suppressed_count: 0
    },
    // 筛选条件
    filters: {
      status: [],           // 多选状态
      user_id: '',
      date_range: [],       // [date_from, date_to]
    },
    // 任务列表
    taskList: [],
    total: 0,
    currentPage: 1,
    pageSize: 20,
    isLoading: false,
    // 自动刷新
    autoRefresh: false,
    refreshTimer: null,
    // 侧抽屉控制
    detailDrawer: { visible: false, taskId: '' },
    traceDrawer:  { visible: false, taskId: '' },
    // 状态选项配置
    statusOptions: [
      { value: 'pending',          label: '待处理' },
      { value: 'queued',           label: '排队中' },
      { value: 'running',          label: '执行中' },
      { value: 'completed',        label: '已完成' },
      { value: 'failed',           label: '失败' },
      { value: 'aborted',          label: '用户中止' },
      { value: 'admin_stopped',    label: '管理员中断' },
      { value: 'violation_pending','label': '合规审核中' },
      { value: 'needs_review',     label: '待人工审核' },
    ]
  }
}
```

---

#### 4.4.3 `DRTaskDetailDrawer.vue`（任务详情侧抽屉）

**职责**：展示任务完整元信息，并在同一面板内提供干预操作按钮

**触发方式**：由 `DRTaskList.vue` 通过 `ref` 调用，或通过 `:visible` / `:taskId` prop 控制

**设计方案**：作为一个独立 Vue 组件，接受 `taskId` prop，内部自行请求详情数据

**布局**：

```
DRTaskDetailDrawer.vue（el-drawer，direction="rtl"，size="40%"）
├── 标题：「任务详情」
├── el-descriptions（任务基本信息）
│   ├── 任务ID
│   ├── 用户名
│   ├── 研究问题（query）
│   ├── 状态（el-tag）
│   ├── 当前阶段
│   ├── 进度（el-progress）
│   ├── 最新步骤摘要（step_summary）
│   ├── Token 消耗
│   ├── 输出状态（已屏蔽/正常）
│   ├── 创建时间
│   ├── 开始时间
│   └── 完成时间
│
├── 分割线：「管理干预」
├── 操作按钮区（根据任务状态动态显示）
│   ├── 强制中断（running/queued 可用）
│   ├── 屏蔽输出（completed + !suppressed 可用）
│   ├── 恢复输出（completed + suppressed 可用）
│   └── 查看审计日志（展开内联表格，调用 getTaskAuditLogs）
│
└── 底部：「查看执行轨迹」按钮（触发父组件打开 DRTraceDrawer）
```

**Props**：
```js
props: {
  taskId: { type: String, required: true }
}
```

---

#### 4.4.4 `DRTraceDrawer.vue`（执行轨迹侧抽屉）

**职责**：以时间线形式展示任务的执行步骤

**设计方案**：作为独立 Vue 组件，接受 `taskId` prop，内部调用 `getDRTaskTrace`

**布局**：

```
DRTraceDrawer.vue（el-drawer，direction="rtl"，size="45%"）
├── 标题：「执行轨迹」+ 任务query简短摘要
├── 任务基本状态信息（status / progress / token_used_total 简短展示）
├── el-timeline（步骤时间线）
│   └── 每个步骤 → el-timeline-item
│       ├── timestamp：created_at
│       ├── color：按 phase 区分颜色
│       │   ├── planning   → #409EFF（蓝）
│       │   ├── searching  → #67C23A（绿）
│       │   ├── reading    → #E6A23C（橙）
│       │   ├── reflecting → #909399（灰）
│       │   └── writing    → #F56C6C（红）
│       ├── 内容：
│       │   ├── 阶段标签（el-tag，按 phase 配色）
│       │   ├── 动作描述（action）
│       │   ├── 步骤摘要（summary，可折叠展开）
│       │   └── Token 消耗（token_used，若 > 0 显示）
│
└── 底部：「刷新轨迹」按钮（对运行中任务可手动刷新获取最新步骤）
```

**阶段中文映射**：

| phase | 中文 | 颜色 |
|-------|------|------|
| planning | 规划 | #409EFF |
| searching | 检索 | #67C23A |
| reading | 阅读 | #E6A23C |
| reflecting | 反思 | #909399 |
| writing | 生成报告 | #F56C6C |

---

#### 4.4.5 `DRAuditLogs.vue`（审计日志）

**职责**：展示全局 DR 操作审计日志，支持多维筛选

**布局**：

```
DRAuditLogs.vue
├── 筛选区
│   ├── el-input：操作管理员名称筛选
│   ├── el-select：操作类型筛选
│   │   选项：强制中断 / 屏蔽输出 / 恢复输出 / 查看轨迹
│   ├── el-date-picker（range）：操作时间范围
│   └── el-button「搜索」
├── el-table（审计日志列表）
│   ├── 列：序号
│   ├── 列：操作管理员（admin）
│   ├── 列：任务ID（截断 + el-tooltip）
│   ├── 列：操作类型（action → el-tag）
│   │   ├── force_stop       → danger
│   │   ├── suppress_output  → warning
│   │   ├── unsuppress_output→ success
│   │   └── view_trace       → info
│   ├── 列：操作原因（reason）
│   └── 列：操作时间（created_at）
└── el-pagination
```

---

## 5. 侧边栏修改

修改 `src/views/layout/LayoutContainer.vue`，在现有菜单项后追加两个新菜单项，并修复 `activeMenu` 计算属性以避免路径前缀冲突：

### 5.1 新增菜单项

```html
<!-- 访问频次控制（在「评论管理」之后追加）-->
<el-menu-item index="/access-frequency">
    <el-icon><i-ep-Odometer /></el-icon>
    <span>频次控制</span>
</el-menu-item>

<!-- Deep Research 监控 -->
<el-menu-item index="/deep-research">
    <el-icon><i-ep-Monitor /></el-icon>
    <span>DR 监控</span>
</el-menu-item>
```

### 5.2 修复 `activeMenu` 计算属性

现有逻辑存在问题：`/report` 前缀同时匹配「用户审核」(`/report`) 和「评论管理」(`/system_report`) 的子路由（后者子路由被错误定义为 `/report/unreverted`、`/report/reverted`）。

建议修复方案：

```js
computed: {
    activeMenu() {
        const path = this.$route.path
        // 用户举报审核 /report/*
        if (path.startsWith('/report/unhandled') || path.startsWith('/report/handled')) {
            return '/report'
        }
        // 评论管理（子路由当前被定义为 /report/unreverted 等，待路由修正后更新此处）
        if (path.startsWith('/report/unreverted') || path.startsWith('/report/reverted')) {
            return '/system_report'
        }
        // 访问频次控制
        if (path.startsWith('/access-frequency')) {
            return '/access-frequency'
        }
        // Deep Research 监控
        if (path.startsWith('/deep-research')) {
            return '/deep-research'
        }
        return path
    }
}
```

> **注**：建议同步修复 `system_report` 路由路径问题（将子路由从 `/report/unreverted` 改为 `/system_report/unreverted`），但此修改可能影响现有功能，需测试验证，可作为独立 issue 处理。

---

## 6. 新增文件清单

```
src/
├── api/
│   ├── access_frequency.js           ← 新增：频次控制 API 函数
│   └── deep_research.js              ← 新增：DR 监控 API 函数
│
└── views/
    ├── access_frequency/
    │   ├── AccessFrequencyManage.vue  ← 新增：频次控制主容器（子菜单导航）
    │   ├── FrequencyRules.vue         ← 新增：规则配置页面
    │   ├── UserOverrides.vue          ← 新增：用户特殊配额页面
    │   └── FrequencyStats.vue         ← 新增：访问统计页面
    │
    └── deep_research/
        ├── DRMonitorManage.vue        ← 新增：DR 监控主容器（子菜单导航）
        ├── DRTaskList.vue             ← 新增：任务监控列表页（核心页面）
        ├── DRAuditLogs.vue            ← 新增：审计日志页面
        ├── DRTaskDetailDrawer.vue     ← 新增：任务详情侧抽屉组件
        └── DRTraceDrawer.vue          ← 新增：执行轨迹侧抽屉组件
```

**合计新增文件**：2 个 API 文件 + 9 个 Vue 组件 = **11 个文件**

---

## 7. 现有文件修改清单

| 文件 | 修改内容 | 影响范围 |
|------|----------|----------|
| `src/router/index.js` | 追加 2 组路由（`/access-frequency/*`、`/deep-research/*`） | 仅新增路由，不影响现有路由 |
| `src/views/layout/LayoutContainer.vue` | 追加 2 个 `el-menu-item`；修复 `activeMenu` 计算属性 | 侧边栏高亮逻辑；不影响现有页面渲染 |

---

## 8. 开发子任务拆分

### 功能一：访问频次控制

| 子任务 | 内容 | 依赖 | 预估工时 |
|--------|------|------|----------|
| F-A1 | 新建 `src/api/access_frequency.js`，封装全部 API 函数 | 后端接口就绪 | 0.5h |
| F-A2 | 新建 `AccessFrequencyManage.vue`（容器 + 子菜单），配置路由，修改侧边栏 | F-A1 | 1h |
| F-A3 | 实现 `FrequencyRules.vue`（规则管理列表 + 新增/编辑/删除 Dialog） | F-A1、F-A2 | 3h |
| F-A4 | 实现 `UserOverrides.vue`（用户覆盖配置管理） | F-A1、F-A2 | 2.5h |
| F-A5 | 实现 `FrequencyStats.vue`（统计概览 + 用户排行 + 用户详情弹窗） | F-A1、F-A2 | 2.5h |

### 功能二：DR 任务监控

| 子任务 | 内容 | 依赖 | 预估工时 |
|--------|------|------|----------|
| F-D1 | 新建 `src/api/deep_research.js`，封装全部 API 函数 | 后端接口就绪 | 0.5h |
| F-D2 | 新建 `DRMonitorManage.vue`（容器 + 子菜单），配置路由，修改侧边栏 | F-D1 | 1h |
| F-D3 | 实现 `DRTraceDrawer.vue`（执行轨迹时间线侧抽屉） | F-D1 | 2h |
| F-D4 | 实现 `DRTaskDetailDrawer.vue`（任务详情 + 干预操作侧抽屉） | F-D1、F-D3 | 3h |
| F-D5 | 实现 `DRTaskList.vue`（核心：统计卡片 + 筛选 + 列表 + 轮询 + 集成 F-D3/F-D4） | F-D1 ~ F-D4 | 4h |
| F-D6 | 实现 `DRAuditLogs.vue`（审计日志列表 + 筛选） | F-D1、F-D2 | 2h |

### 建议开发顺序

```
第一阶段（可并行）：
  ├── F-A1 + F-A2 → F-A3（最核心的规则管理）
  └── F-D1 + F-D2 → F-D3 + F-D4

第二阶段（顺序进行）：
  ├── F-A4 + F-A5
  └── F-D5 + F-D6（F-D5 最复杂，最后联调）

第三阶段：
  └── 修复 activeMenu 计算属性 + 整体联调测试
```

---

## 附录：常量与样式约定

### 状态颜色映射

```js
// DR 任务状态 → Element Plus Tag type
const DR_STATUS_TAG = {
    pending:          'info',
    queued:           'info',
    running:          'warning',
    completed:        'success',
    failed:           'danger',
    aborted:          'info',
    admin_stopped:    'danger',
    violation_pending:'warning',
    needs_review:     'warning',
    archived:         'info'
}

// DR 任务状态 → 中文文本
const DR_STATUS_LABEL = {
    pending:          '待处理',
    queued:           '排队中',
    running:          '执行中',
    completed:        '已完成',
    failed:           '失败',
    aborted:          '用户中止',
    admin_stopped:    '管理员中断',
    violation_pending:'合规审核中',
    needs_review:     '待人工审核',
    archived:         '已归档'
}
```

### Token 数字格式化工具函数

```js
// 在组件内或提取到 utils/format.js
function formatToken(num) {
    if (num >= 10000) return (num / 10000).toFixed(1) + ' 万'
    return num.toString()
}
```

### 轮询防重入处理

```js
// DRTaskList.vue 中，避免请求还未返回时再次发起
async fetchTaskList() {
    if (this.isLoading) return
    this.isLoading = true
    try {
        const res = await getDRTaskList({ ...this.filters, page_num: this.currentPage, page_size: this.pageSize })
        this.taskList = res.data.items
        this.total = res.data.total
    } catch (e) {
        ElMessage.error('获取任务列表失败')
    } finally {
        this.isLoading = false
    }
}
```

---

*文档版本：v0.1 | 编写日期：2026-04-18 | 作者：管理端前端开发*
