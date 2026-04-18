# EPP 学术文献科研助手 — 前端项目说明文档

> 面向不了解前端开发的读者撰写。本文档涵盖：技术栈快速入门、项目目录结构、核心文件功能说明、页面路由地图、API 接口层说明。

---

## 第一章：技术栈快速入门

> 如果你已熟悉 Vue 2 / Webpack 生态，可跳过本章，直接阅读第二章。

### 1.1 什么是"前端"

用户用浏览器打开一个网页应用时，浏览器下载并运行的那部分代码，就是**前端**。前端负责：

- 把数据渲染成界面（按钮、列表、图表……）
- 响应用户操作（点击、输入……）
- 通过网络请求与后端服务器交换数据

前端代码由三种语言组成：**HTML**（结构）、**CSS**（样式）、**JavaScript**（逻辑）。

---

### 1.2 Vue 2 —— 核心框架

本项目使用 **[Vue 2](https://v2.vuejs.org/)**（当前最稳定的成熟版本）。

**核心思想：组件化**

Vue 把界面拆成一个个独立的"组件"（Component），每个组件是一个 `.vue` 文件，包含三块：

```html
<!-- 示例：MyButton.vue -->

<template>
  <!-- HTML 结构：描述这个组件长什么样 -->
  <button @click="handleClick">{{ label }}</button>
</template>

<script>
// JavaScript 逻辑：数据、方法
export default {
  name: 'MyButton',
  props: ['label'],          // 父组件传进来的参数
  data() {
    return { count: 0 }      // 这个组件自己的数据
  },
  methods: {
    handleClick() {
      this.count++
    }
  }
}
</script>

<style scoped>
/* CSS 样式：只作用于本组件 */
button { background: blue; color: white; }
</style>
```

**关键概念速查：**

| 概念 | 简单解释 |
|------|----------|
| `data()` | 组件的私有数据，数据变化时界面自动刷新 |
| `props` | 父组件传给子组件的参数（只读） |
| `methods` | 组件的函数/方法 |
| `computed` | 基于 data 计算出的衍生值，自动缓存 |
| `mounted()` | 生命周期钩子：组件挂载到页面后执行一次（常用于发网络请求） |
| `v-if` | 条件渲染：`<div v-if="show">` 只在 show 为 true 时显示 |
| `v-for` | 列表渲染：`<li v-for="item in list">` |
| `v-bind` / `:` | 动态绑定属性：`:href="url"` |
| `v-on` / `@` | 绑定事件：`@click="doSomething"` |
| `v-model` | 双向绑定表单：输入框内容与变量实时同步 |

---

### 1.3 Vue Router —— 页面路由

一个"单页应用"（SPA）只有一个 HTML 文件，但可以显示多个"页面"。**Vue Router** 通过监听 URL 变化，决定渲染哪个组件，模拟出多页面的效果。

```
用户访问 /search     → 渲染 SearchPage.vue
用户访问 /personal   → 渲染 PersonalMain.vue
```

本项目路由配置在 `src/router/index.js`。

---

### 1.4 Axios —— 网络请求

**Axios** 是最流行的 JavaScript HTTP 请求库，用于前端与后端 API 通信：

```javascript
// 发一个 GET 请求
axios.get('/api/papers').then(response => {
  console.log(response.data) // 后端返回的数据
})

// 发一个 POST 请求
axios.post('/api/login', { username: 'alice', password: '123' })
```

本项目对 Axios 进行了封装，见 `src/request/` 目录。

---

### 1.5 Element UI —— UI 组件库

**[Element UI](https://element.eleme.io/#/zh-CN)** 是饿了么开源的 Vue 2 组件库，提供现成的美观组件：

```html
<!-- 直接使用，无需自己写样式 -->
<el-button type="primary">主要按钮</el-button>
<el-input v-model="keyword" placeholder="请输入关键词" />
<el-table :data="papers">...</el-table>
<el-dialog :visible.sync="showDialog" title="详情">...</el-dialog>
```

所有以 `el-` 开头的标签都是 Element UI 组件。

---

### 1.6 Webpack —— 打包构建工具

**Webpack** 把 `src/` 下所有 `.vue`、`.js`、CSS、图片等文件，打包成浏览器能直接运行的静态资源（HTML + JS + CSS）。

- **开发时**：运行 `yarn run dev`，Webpack 启动本地服务器，支持热更新（修改代码后浏览器自动刷新）
- **发布时**：运行 `yarn run build`，生成优化后的 `dist/` 目录，部署到 Web 服务器

---

### 1.7 EventBus —— 跨组件通信

本项目没有引入 Vuex（大型状态管理库），而是用一个轻量的 **EventBus** 模式来让不同组件互相通信：

```javascript
// 组件 A：发射事件
EventBus.$emit('paperSelected', paperData)

// 组件 B：监听事件
EventBus.$on('paperSelected', (data) => { /* 处理 */ })
```

---

## 第二章：项目目录结构

```
EPP-Frontend-Dev/
│
├── src/                        ← 【核心】所有源代码都在这里
│   ├── main.js                 ← 应用入口，初始化 Vue
│   ├── App.vue                 ← 根组件（顶层布局）
│   │
│   ├── router/
│   │   └── index.js            ← 路由配置（URL → 组件 的映射表）
│   │
│   ├── request/
│   │   ├── request.js          ← Axios 实例（基础封装，已标注"可能废弃"）
│   │   └── userRequest.js      ← 所有 API 请求函数（登录/收藏/上传等）
│   │
│   ├── mock/
│   │   ├── index.js            ← Mock 初始化（开发环境拦截请求返回假数据）
│   │   └── user.js             ← 用户相关 Mock 数据定义
│   │
│   ├── utils/
│   │   └── eventBus.js         ← 跨组件通信总线
│   │
│   ├── components/             ← 所有 Vue 组件（按功能模块分目录）
│   │   ├── About.vue
│   │   ├── HelloWorld.vue
│   │   ├── NavBar.vue          ← 顶部全局导航栏
│   │   ├── Main/               ← 首页 / 登录模块
│   │   ├── Search/             ← 文献搜索模块
│   │   ├── PaperInfo/          ← 论文详情模块
│   │   ├── PaperRead/          ← 论文阅读 / PDF 查看模块
│   │   ├── UploadDocuments/    ← 文档上传模块
│   │   └── Personal/           ← 个人中心模块
│   │
│   └── assets/
│       └── icon/               ← SVG 图标资源（导航栏、按钮图标等）
│
├── build/                      ← Webpack 构建配置（一般无需修改）
│   ├── webpack.base.conf.js    ← 公共配置
│   ├── webpack.dev.conf.js     ← 开发环境配置
│   ├── webpack.prod.conf.js    ← 生产环境配置
│   └── build.js                ← 生产构建脚本
│
├── config/                     ← 环境变量配置
│   ├── index.js                ← 端口、路径等通用配置
│   ├── dev.env.js              ← 开发环境变量（API 地址等）
│   └── prod.env.js             ← 生产环境变量
│
├── static/                     ← 静态资源（不经过 Webpack 处理）
│   ├── favicon.png
│   └── css/bulma.css           ← Bulma CSS 框架
│
├── index.html                  ← SPA 唯一的 HTML 模板
├── package.json                ← 项目元信息与依赖声明
└── yarn.lock                   ← 依赖版本锁定文件
```

---

## 第三章：核心文件功能说明

### 3.1 应用入口 `src/main.js`

整个应用的**启动文件**，做三件事：

1. **注册全局插件**：Element UI、Bootstrap-Vue
2. **注入全局变量**：
   - `Vue.prototype.$BASE_URL` — 后端服务器根地址（如 `http://127.0.0.1:8000`）
   - `Vue.prototype.$BASE_API_URL` — API 根地址（如 `http://127.0.0.1:8000/api`）
3. **启动 Mock**：开发环境下自动开启假数据拦截，无需后端也能运行

```javascript
// 在任意组件中都可以这样用：
this.$BASE_URL         // 后端根地址
this.$BASE_API_URL     // API 根地址
```

---

### 3.2 根组件 `src/App.vue`

整个应用的**外壳**，包含：

- **条件性顶部导航栏**：根据当前路由的 `meta.hideNavbar` 决定是否显示 `<NavBar />`
- **路由出口 `<router-view/>`**：当前路由匹配到的页面组件渲染在这里
- **全局滚动条样式**：统一的美化滚动条

> 如果某个页面不想显示顶部导航栏（如仪表盘/登录页），在路由配置中设置 `meta: { hideNavbar: true }` 即可。

---

### 3.3 路由配置 `src/router/index.js`

定义了应用的**所有页面 URL**：

| URL 路径 | 对应组件 | 显示导航栏 | 说明 |
|----------|----------|-----------|------|
| `/` | 重定向到 `/dashboard` | 是 | 根路径 |
| `/dashboard` | `Main/Dashboard.vue` | **否** | 首页/登录页 |
| `/search` | `Search/SearchPage.vue` | 是 | 文献搜索输入页 |
| `/search/results` | `Search/SearchResult.vue` | 是 | 搜索结果页 |
| `/paper/info/:paper_id` | `PaperInfo/PaperInfo.vue` | 是 | 论文详情页 |
| `/paper/reader/:paper_id` | `PaperRead/PaperReader.vue` | 是 | 在线 PDF 阅读页 |
| `/paper/annotations/:paper_id` | `PaperRead/PdfAnnotations.vue` | 是 | PDF 批注页 |
| `/paper/localReader/:paper_id` | `PaperRead/LocalPaperReader.vue` | 是 | 本地 PDF 阅读页 |
| `/personal` | `Personal/PersonalMain.vue` | 是 | 个人中心 |
| `/upload` | `UploadDocuments/UploadDocuMain.vue` | 是 | 文档上传页 |

> `:paper_id` 是动态路由参数，例如访问 `/paper/info/12345` 时，组件内通过 `this.$route.params.paper_id` 获取值 `"12345"`。

---

### 3.4 API 请求层 `src/request/`

#### `request.js` — Axios 基础实例（底层）

- 创建一个 baseURL 为 `/api` 的 Axios 实例
- **请求拦截器**：自动在请求头中加入 JWT Token（从 `localStorage` 读取）
- **响应拦截器**：统一处理返回数据格式
- 注：文件顶部注释标注了"This file seems useless!"，说明此文件现为被 `userRequest.js` 内部调用的底层工具

#### `userRequest.js` — 业务 API 函数（上层）

封装了所有与后端通信的函数，其他组件通过 `import { login } from '../request/userRequest'` 引入使用：

| 函数名 | HTTP 方法 | 接口路径 | 说明 |
|--------|-----------|----------|------|
| `login(params)` | POST | `/login` | 用户登录，成功后存储 JWT Token |
| `logout()` | GET | `/logout` | 退出登录，清除 Cookie |
| `register(params)` | POST | `/sign` | 用户注册 |
| `fetchUserInfo()` | GET | `/userInfo/userInfo` | 获取当前用户信息 |
| `fetchCollectedPapers()` | GET | `/userInfo/collectedPapers` | 获取收藏的论文 |
| `deleteCollectedPapers(data)` | DELETE | `/userInfo/delCollectedPapers` | 删除收藏 |
| `fetchTranslations()` | GET | `/userInfo/translations` | 获取翻译历史 |
| `deleteTranslation(id)` | DELETE | `/userInfo/translation/:id` | 删除翻译记录 |
| `fetchSearchHistory()` | GET | `/userInfo/searchHistory` | 获取搜索历史 |
| `deleteSearchHistory(params)` | DELETE | `/userInfo/delSearchHistory` | 删除搜索历史 |
| `fetchReports()` | GET | `/userInfo/summaryReports` | 获取 AI 生成的摘要报告 |
| `fetchReportContent(params)` | GET | `/userInfo/getSummary` | 获取单份报告内容 |
| `deleteReport(data)` | DELETE | `/userInfo/delSummaryReports` | 删除报告 |
| `fetchChat()` | GET | `/userInfo/paperReading` | 获取阅读助手对话历史 |
| `deleteChat(data)` | DELETE | `/userInfo/delPaperReading` | 删除对话记录 |
| `fetchDocument()` | GET | `/userInfo/documents` | 获取已上传文档列表 |
| `uploadDocument(formData)` | POST | `/uploadPaper` | 上传论文文档 |
| `deleteDocument(params)` | POST | `/removeUploadedPaper` | 删除已上传文档 |
| `fetchNotification(mode)` | GET | `/userInfo/notices` | 获取消息通知 |
| `deleteNotification(data)` | DELETE | `/userInfo/delNotices` | 删除通知 |
| `readNotification(data)` | POST | `/userInfo/readNotices` | 标记通知为已读 |
| `fetchAnnotations(paperID)` | GET | `/paper/annotations` | 获取论文批注列表 |
| `addAnnotation(paperID, params)` | PUT | `/paper/annotation` | 新增批注 |
| `annotationLike(annotationID)` | POST | `/annotation/like/toggle` | 批注点赞/取消 |
| `annotationComment(...)` | PUT | `/annotation/comment` | 新增批注评论 |
| `fetchAnnotationComment(id)` | GET | `/annotation/comments` | 获取批注评论 |
| `userVisitRecord()` | POST | `/manage/recordVisit` | 记录用户访问（统计用） |

**认证机制：** 登录成功后，JWT Token 存入 `localStorage`，后续每次请求自动携带。登录状态也通过 Cookie `userlogin` 维持。

---

### 3.5 组件详解

#### 全局导航 `components/NavBar.vue`

顶部全局导航栏，出现在除 Dashboard 以外的所有页面顶部，提供页面间导航链接。

---

#### 首页/登录模块 `components/Main/`

| 文件 | 功能 |
|------|------|
| `Dashboard.vue` | 应用主页/登录落地页（不显示顶部导航栏），整合了登录表单和首页展示 |
| `Login.vue` | 登录/注册表单组件 |
| `Buttons.vue` | 首页快捷操作按钮组 |
| `ImageCarousel.vue` | 首页图片轮播展示（展示热门论文或功能介绍） |

---

#### 文献搜索模块 `components/Search/`

| 文件 | 功能 |
|------|------|
| `SearchPage.vue` | 搜索主页（路由 `/search`），包含搜索输入框 |
| `SearchInput.vue` | 搜索输入框组件，处理关键词输入与提交 |
| `SearchResult.vue` | 搜索结果列表页（路由 `/search/results`） |
| `PaperCard.vue` | 单篇论文的卡片展示组件，在搜索结果列表中复用 |
| `SearchAssistant.vue` | AI 搜索助手侧边栏，辅助用户优化搜索策略 |

---

#### 论文详情模块 `components/PaperInfo/`

| 文件 | 功能 |
|------|------|
| `PaperInfo.vue` | 论文详情页（路由 `/paper/info/:paper_id`），展示标题、摘要、作者、引用等元数据；提供收藏、引用、阅读操作入口 |
| `ReportModal.vue` | 弹出式 AI 摘要报告生成/查看面板 |

---

#### 论文阅读模块 `components/PaperRead/`

| 文件 | 功能 |
|------|------|
| `PaperReader.vue` | 在线论文阅读主页面（路由 `/paper/reader/:paper_id`），整合 PDF 查看与 AI 助手 |
| `PdfViewer.vue` | PDF 渲染组件（基于 `vue-pdf` 库），负责显示 PDF 内容 |
| `ReadAssistant.vue` | AI 阅读助手聊天面板（在线论文），支持对话式提问 |
| `Annotations.vue` | 批注展示与管理面板（列表、点赞、评论） |
| `NoteEditor.vue` | 笔记编辑器（基于 `vditor` Markdown 编辑器） |
| `LocalPaperReader.vue` | 本地 PDF 阅读页（路由 `/paper/localReader/:paper_id`），阅读用户上传的本地文件 |
| `LocalReadAssistant.vue` | AI 阅读助手（针对本地上传论文） |
| `PdfAnnotations.vue` | PDF 批注页（路由 `/paper/annotations/:paper_id`），支持在 PDF 上直接标注 |

---

#### 文档上传模块 `components/UploadDocuments/`

| 文件 | 功能 |
|------|------|
| `UploadDocuMain.vue` | 文档上传主页面（路由 `/upload`），整合导航与内容区域 |
| `UploadDocuNavbar.vue` | 上传页面内部的侧边导航栏（切换"上传"与"文档列表"） |
| `Upload.vue` | 文件上传表单组件，处理文件选择与上传到后端 |
| `Documents.vue` | 已上传文档的列表管理，支持查看和删除 |

---

#### 个人中心模块 `components/Personal/`

| 文件 | 功能 |
|------|------|
| `PersonalMain.vue` | 个人中心主页面（路由 `/personal`），内嵌左侧导航 + 内容区域 |
| `PersonalNavBar.vue` | 个人中心左侧功能导航栏（切换各子功能页） |
| `PersonalInfo.vue` | 个人信息页：展示用户名、头像、注册时间、收藏数、点赞数 |
| `PersonalCollections.vue` | 我的收藏：展示和管理已收藏论文 |
| `PersonalSearch.vue` | 搜索历史：查看和删除历史搜索记录 |
| `PersonalChat.vue` | AI 对话历史：查看与阅读助手的历史聊天记录 |
| `PersonalReport.vue` | AI 报告历史：查看和下载已生成的 AI 摘要报告 |
| `PersonalTranslations.vue` | 翻译历史：查看和管理翻译过的内容记录 |
| `PersonalNotices.vue` | 消息通知：查看、标记已读、删除系统通知 |
| `UploadDocument.vue` | 在个人中心入口上传论文（与 UploadDocuments 模块功能相似） |

---

### 3.6 Mock 数据 `src/mock/`

**作用：** 在前端开发时，后端接口可能尚未就绪。Mock 通过拦截 HTTP 请求，直接返回预设的假数据，让前端可以独立开发调试。

- 仅在 `NODE_ENV === 'development'`（开发环境）时生效
- `index.js` 初始化 Mock.js，设置模拟延迟 200~600ms（模拟真实网络）
- `user.js` 定义用户相关接口的 Mock 响应数据

---

### 3.7 通信工具 `src/utils/eventBus.js`

```javascript
import Vue from 'vue'
export const EventBus = new Vue()
```

仅 3 行，但很重要。EventBus 是一个空的 Vue 实例，利用 Vue 的事件系统作为**跨组件消息总线**。

典型场景：PDF 阅读页中，`PdfViewer` 组件选中了文字 → 通过 EventBus 发射事件 → `ReadAssistant` 组件接收到，自动填充到提问框。

> 注意：`src/main.js` 中也导出了一个 `EventBus`，两者功能相同，使用时注意统一从同一个文件导入，避免混乱。

---

## 第四章：环境配置与 API 地址

### 4.1 开发环境 `config/dev.env.js`

```javascript
VUE_APP_ROOT: '"http://127.0.0.1:8000"'       // 后端本地服务器地址
VUE_APP_API_ROOT: '"http://127.0.0.1:8000/api"' // 后端 API 根路径
```

**说明：** 开发时前端跑在 `http://localhost:8080`，后端跑在 `http://127.0.0.1:8000`。实际请求会走 Webpack 代理（配置在 `config/index.js` 的 `proxyTable`），避免跨域问题。

### 4.2 生产环境 `config/prod.env.js`

```javascript
VUE_APP_ROOT: '"http://api.example.com:8080"'
VUE_APP_API_ROOT: '"http://api.example.com:8080/api"'
```

**说明：** 部署前需修改这里的地址为实际生产服务器地址。

---

## 第五章：如何运行项目

### 5.1 环境准备

1. 安装 [Node.js](https://nodejs.org/)，推荐版本 `v22.11.0`
2. 安装 yarn：`npm install -g yarn`

### 5.2 安装依赖

```bash
cd EPP-Frontend-Dev
yarn install
```

### 5.3 启动开发服务器

```bash
yarn run dev
```

启动后访问 `http://localhost:8080`（端口见 `config/index.js`）。

### 5.4 构建生产版本

```bash
yarn run build
```

输出目录为 `dist/`，将其部署到 Nginx 或其他 Web 服务器即可。

---

## 第六章：依赖库清单

| 库名 | 版本 | 用途 |
|------|------|------|
| `vue` | 2.5.x | 核心框架 |
| `vue-router` | 3.x | 前端路由 |
| `axios` | 0.19.x | HTTP 请求 |
| `element-ui` | 2.15.x | UI 组件库（表单、对话框、表格等） |
| `bootstrap` + `bootstrap-vue` | 5.x / 2.x | 响应式布局与 Bootstrap 组件 |
| `@fortawesome/fontawesome-free` | 6.x | Font Awesome 图标字体 |
| `vue-pdf` | 4.3.x | PDF 渲染组件 |
| `vditor` | 3.11.x | Markdown 富文本编辑器（笔记功能） |
| `markdown-it` / `marked` | 14.x / 12.x | Markdown 解析渲染（AI 回复渲染） |
| `highlight.js` | 11.x | 代码高亮（AI 回复中的代码块） |
| `mockjs` | 1.1.x | 开发阶段 Mock 数据 |
| `html2pdf.js` / `jspdf` | 0.10.x / 2.5.x | PDF 导出功能 |
| `webpack` | 3.x | 打包构建工具 |

---

## 附录：项目功能全景图

```
学术文献科研助手
│
├── 首页 / 登录 (/dashboard)
│   ├── 用户登录 / 注册
│   └── 首页展示（热门论文轮播、快捷操作按钮）
│
├── 文献搜索 (/search → /search/results)
│   ├── 关键词搜索
│   ├── 搜索结果卡片列表
│   └── AI 搜索助手（侧边对话）
│
├── 论文详情 (/paper/info/:id)
│   ├── 元数据展示（标题、摘要、作者、发表时间等）
│   ├── 收藏 / 点赞 / 引用
│   └── AI 摘要报告生成
│
├── 论文阅读 (/paper/reader/:id)
│   ├── PDF 在线查看
│   ├── AI 阅读助手（对话式提问）
│   ├── 批注功能（查看 / 添加 / 点赞 / 评论）
│   └── Markdown 笔记编辑器
│
├── 本地 PDF 阅读 (/paper/localReader/:id)
│   ├── 用户上传的 PDF 查看
│   └── AI 阅读助手（针对本地文件）
│
├── 文档上传 (/upload)
│   ├── 上传本地 PDF 文档
│   └── 已上传文档管理（查看 / 删除）
│
└── 个人中心 (/personal)
    ├── 个人信息（头像、统计数据）
    ├── 我的收藏
    ├── 搜索历史
    ├── AI 对话历史
    ├── AI 报告历史
    ├── 翻译历史
    └── 消息通知
```
