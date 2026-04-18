# EPP-Frontend-Dev（用户端前端）

EPP 文献调研助手用户端前端项目，基于 Vue2 + Webpack 构建，负责用户侧页面交互与业务流程（检索、阅读、摘要、推荐等）的展示与调用。

## 1. 仓库内容概览

本项目为独立前端工程，核心目录如下：

- `src/`：页面、组件、路由与业务逻辑
- `config/`：环境配置（`dev.env.js` / `prod.env.js`）
- `build/`：Webpack 构建配置与脚本
- `static/`：静态资源
- `index.html`：应用入口模板
- `package.json`：依赖与脚本入口

## 2. 技术栈

- Vue `2.5.2`
- Vue Router `3.x`
- Webpack `3.x` + `webpack-dev-server`
- Element UI、Bootstrap Vue
- Axios（接口请求）
- Yarn `1.22.x`
- Node.js：建议 `22.11.0`（推荐 `>=20`）

## 3. 配置说明

用户端环境变量通过 `config/dev.env.js` 与 `config/prod.env.js` 管理。  
在 mono-repo 中，推荐通过 `EPP-Configuration/link.sh` 统一建立链接。

### 3.1 本地开发配置（示例）

`config/dev.env.js` 关键字段：

- `VUE_APP_ROOT`：后端根地址（例如 `http://127.0.0.1:8000`）
- `VUE_APP_API_ROOT`：后端 API 地址（例如 `http://127.0.0.1:8000/api`）

### 3.2 配置链接（推荐）

在根目录执行：（替换为实际路径）

```bash
cd /home/Spencer/projects/SE_project/EPP-Configuration
bash link.sh
```

会自动建立：

- `EPP-Frontend-Dev/config/dev.env.js`
- `EPP-Frontend-Dev/config/prod.env.js`

## 4. 本地开发启动

### 4.1 安装依赖

```bash
yarn install --network-timeout 600000
```

### 4.2 启动开发服务

```bash
yarn run dev
```

默认端口：`8080`  
默认访问地址：`http://127.0.0.1:8080`

### 4.3 构建生产包

```bash
yarn run build
```

## 5. 可用脚本

- `yarn run dev`：启动本地开发服务
- `yarn run build`：打包生产构建
- `yarn run lint`：执行 ESLint 检查

## 6. 与后端联调

联调前请确保后端已启动（默认 `127.0.0.1:8000`），并确认后端 `CORS_ALLOWED_ORIGINS` 已包含：

- `http://localhost:8080`
- `http://127.0.0.1:8080`

若后端地址变化，需同步修改 `config/dev.env.js` 中的 `VUE_APP_ROOT` 与 `VUE_APP_API_ROOT`。

## 7. 常见问题（FAQ）

- 启动时报错缺少 `build/webpack.dev.conf.js`
  - 说明：`build/` 目录缺失或迁移不完整
  - 处理：补齐 `build/` 后重新执行 `yarn run dev`
- `yarn install` 下载慢/超时
  - 处理：使用 `--network-timeout 600000` 并重试
- 启动后页面 404 或接口异常
  - 检查 `dev.env.js` 的后端地址是否正确
  - 检查后端是否已启动且跨域配置正确

## 8. 开发建议

- 统一使用 Yarn（避免 `package-lock.json` 与 `yarn.lock` 混用）
- 配置变更优先在 `EPP-Configuration` 修改，再通过 `link.sh` 同步
- 提交前至少执行一次 `yarn run lint`
