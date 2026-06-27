# EPP-Frontend-Manager-Dev

## 环境要求

- Node.js 建议 `>=20`（推荐 `22.x`）
- 包管理：Yarn `1.22.x`（使用 `yarn.lock`，勿混用 npm）
- 联调时需后端已启动（默认 `http://127.0.0.1:8000`）

## 配置

环境变量通过 Vite 的 `.env.development` / `.env.production` 加载，由 `EPP-Configuration/link.sh` 软链接到配置中心。

### 首次配置

在 mono-repo 根目录执行：

```bash
cd EPP-Configuration
bash link.sh
```

会自动建立：

- `.env.development` → `EPP-Configuration/frontend/manager-frontend/.env.development`
- `.env.production` → `EPP-Configuration/frontend/manager-frontend/.env.production`

若本地文件不存在，脚本从 `*.template` 复制生成。

### 关键配置项

| 文件 | 变量 | 说明 |
|------|------|------|
| `.env.development` | `VITE_API_BASE_URL` | 后端根地址，默认 `http://localhost:8000` |
| `.env.production` | `VITE_API_BASE_URL` | 生产环境后端地址 |

Axios 基址在 `src/utils/request.js` 中读取 `import.meta.env.VITE_API_BASE_URL`。

配置变更在 `EPP-Configuration/frontend/manager-frontend/` 下编辑实际文件后，**重启** `yarn run dev`（Vite 不会热更新 `.env` 变更）。

## 启动

```bash
# 安装依赖
yarn install --network-timeout 600000

# 开发模式
yarn run dev
```

默认端口：`5173`（被占用时 Vite 自动尝试下一端口，以终端 `Local` 地址为准）

## 构建

```bash
yarn run build     # 生产构建
yarn run preview   # 本地预览构建结果
yarn run lint      # ESLint（带 --fix）
yarn run format    # Prettier 格式化 src/
```

## 与后端联调

1. 启动后端（`127.0.0.1:8000`）
2. 确认 `.env.development` 中 `VITE_API_BASE_URL` 指向正确后端
3. 确认后端 `CORS_ALLOWED_ORIGINS` 包含当前前端地址（默认含 `http://localhost:5173`）

若 Vite 使用了非 `5173` 端口，需在后端 CORS 中追加实际 origin。

## 常见问题

- **缺少 `.env.development`**  
  执行 `EPP-Configuration/link.sh`。

- **修改 `.env` 后未生效**  
  重启 `yarn run dev`。

- **接口失败 / 跨域**  
  检查 `VITE_API_BASE_URL`、后端是否运行、CORS 是否包含当前前端端口。

- **`yarn install` 超时**  
  使用 `--network-timeout 600000` 后重试。
