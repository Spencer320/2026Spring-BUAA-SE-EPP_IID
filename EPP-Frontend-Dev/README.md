# EPP-Frontend-Dev

## 环境要求

- Node.js 建议 `>=20`（推荐 `22.x`）
- 包管理：Yarn `1.22.x`（使用 `yarn.lock`，勿混用 npm）
- 联调时需后端已启动（默认 `http://127.0.0.1:8000`）

## 配置

环境变量通过 `config/dev.env.js`（开发）与 `config/prod.env.js`（生产构建）注入，由 `EPP-Configuration/link.sh` 软链接到配置中心。

### 首次配置

在 mono-repo 根目录执行：

```bash
cd EPP-Configuration
bash link.sh
```

会自动建立：

- `config/dev.env.js` → `EPP-Configuration/frontend/user-frontend/dev.env.js`
- `config/prod.env.js` → `EPP-Configuration/frontend/user-frontend/prod.env.js`

若本地文件不存在，脚本从 `*.template` 复制生成。

### 关键配置项

| 文件 | 变量 | 说明 |
|------|------|------|
| `dev.env.js` | `VUE_APP_ROOT` | 后端根地址，如 `http://127.0.0.1:8000` |
| `dev.env.js` | `VUE_APP_API_ROOT` | 后端 API 地址，如 `http://127.0.0.1:8000/api` |
| `prod.env.js` | 同上 | 生产构建时的后端地址 |

开发模式下，Webpack dev server 还将 `/api`、`/resource` 代理到 `http://127.0.0.1:8000`（见 `config/index.js` 的 `proxyTable`）。若后端端口变更，需同步修改代理目标与 `dev.env.js`。

配置变更在 `EPP-Configuration/frontend/user-frontend/` 下编辑实际文件即可。

## 启动

```bash
# 安装依赖
yarn install --network-timeout 600000

# 开发模式
yarn run dev
```

默认端口：`8080`  
访问地址：`http://127.0.0.1:8080`（端口被占用时 Webpack 会自动选用其他端口，以终端输出为准）

## 构建

```bash
yarn run build    # 生产构建，输出到 dist/
yarn run lint     # ESLint 检查
```

## 与后端联调

1. 启动后端（`127.0.0.1:8000`）
2. 确认后端 `CORS_ALLOWED_ORIGINS` 包含 `http://localhost:8080` 与 `http://127.0.0.1:8080`
3. 若后端地址非默认值，更新 `EPP-Configuration/frontend/user-frontend/dev.env.js` 及 `config/index.js` 中的代理目标

## 常见问题

- **缺少 `config/dev.env.js`**  
  执行 `EPP-Configuration/link.sh`。

- **`yarn install` 超时**  
  使用 `--network-timeout 600000` 后重试。

- **接口 404 或跨域**  
  检查后端是否运行、`dev.env.js` 地址是否正确、后端 CORS 是否放行当前前端 origin。

- **缺少 `build/webpack.dev.conf.js`**  
  确认 `build/` 目录完整后再启动。
