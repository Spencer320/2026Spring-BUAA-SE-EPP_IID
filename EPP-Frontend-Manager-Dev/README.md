# EPP-Frontend-Manager-Dev（管理端前端）

EPP 文献调研助手管理后台前端项目，基于 Vue3 + Vite 构建，负责管理员侧的数据管理、统计展示、审核与系统管理功能。

## 1. 仓库内容概览

本项目为独立前端工程，核心目录如下：

- `src/`：页面、组件、路由、状态管理与业务逻辑
- `public/`：静态公共资源
- `vite.config.js`：Vite 构建与开发服务配置
- `.env.development` / `.env.production`：环境变量配置（由配置中心链接）
- `package.json`：依赖与脚本入口

## 2. 技术栈

- Vue `3.x`
- Vite `5.x`
- Vue Router `4.x`
- Vuex `4.x`
- Element Plus
- Axios
- ECharts（可视化）
- Yarn `1.22.x`
- Node.js：建议 `22.11.0`（推荐 `>=20`）

## 3. 配置说明

项目通过 `.env.*` 文件读取环境变量，当前主要使用：

- `VITE_API_BASE_URL`：后端服务根地址

### 3.1 配置来源（推荐）

在 mono-repo 根目录执行：（替换为实际路径）

```bash
cd /home/Spencer/projects/SE_project/EPP-Configuration
bash link.sh
```

会自动建立：

- `EPP-Frontend-Manager-Dev/.env.development`
- `EPP-Frontend-Manager-Dev/.env.production`

默认本地开发值通常为：

```env
VITE_API_BASE_URL=http://localhost:8000
```

## 4. 本地开发启动

### 4.1 安装依赖

```bash
yarn install --network-timeout 600000
```

### 4.2 启动开发服务

```bash
yarn run dev
```

默认端口：`5173`（若被占用，Vite 会自动尝试下一个端口）

### 4.3 生产构建与预览

```bash
yarn run build
yarn run preview
```

## 5. 可用脚本

- `yarn run dev`：启动开发服务
- `yarn run build`：构建生产包
- `yarn run preview`：本地预览构建结果
- `yarn run lint`：执行 ESLint（带 `--fix`）
- `yarn run format`：按 Prettier 格式化 `src/`

## 6. 与后端联调

联调前请确保后端服务已启动（默认 `127.0.0.1:8000`），并在后端跨域配置中包含管理端地址（如 `http://localhost:5173`）。

如果本地开发端口不是 `5173`（例如自动切到 `5174/5175`），请同步确认后端允许该来源访问，避免跨域报错。

## 7. 常见问题（FAQ）

- 启动后端口不是 `5173`
  - 说明：`5173` 被占用，Vite 自动回退到其他端口
  - 处理：查看终端输出中的 `Local` 地址访问
- 接口请求失败 / 跨域报错
  - 检查 `.env.development` 中 `VITE_API_BASE_URL`
  - 检查后端 `CORS_ALLOWED_ORIGINS` 是否包含当前前端地址
- 环境变量修改后未生效
  - 重启 `yarn run dev`，Vite 不会对 `.env` 变更全部热更新

## 8. 开发建议

- 统一使用 Yarn，避免锁文件混用
- 配置变更优先在 `EPP-Configuration` 修改并重新链接
- 提交前建议执行：
  - `yarn run lint`
  - `yarn run build`
