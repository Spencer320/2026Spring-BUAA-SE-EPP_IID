# EPP 评审环境部署文档

> **当前评审入口（唯一推荐）**：`http://114.116.202.158:8080`（用户端） / `http://114.116.202.158:5173`（管理端）  
> 服务器 IP：`114.116.202.158`  
> **80/443 与域名**：课程组服务器无法备案，公网 80/443 及无端口域名访问不可用；评审仅使用 **8080、5173 + 公网 IP**  
> 最后更新：2026-05-21

---

## 0. 当前访问方式（8080 / 5173 + IP）

| 用途 | URL |
|------|-----|
| 用户端 | http://114.116.202.158:8080/ |
| 管理端 | http://114.116.202.158:5173/ |
| API | 与页面同端口，`/api/...`（Nginx 反代到本机 Gunicorn `:8000`） |

**注意：**

- 必须带端口；`http://114.116.202.158`（无端口）走 80，不可用。
- 不要使用 `runserver` / `yarn run dev` 与 Nginx 同时占用 8080/5173；评审环境应使用下文 **生产栈**（Nginx + Gunicorn + systemd）。
- 前端构建产物中的 API 地址已写死为上述 IP，改 IP 后须重新 `yarn build` 并复制到 `/var/www/epp/`。

自测：

```bash
curl -I http://114.116.202.158:8080/
curl -I http://114.116.202.158:5173/
systemctl status epp-backend nginx
```

---

## 1. 架构与技术原理

### 1.1 整体架构

```
浏览器
   ├─ :8080 → Nginx → 用户端静态（/var/www/epp/user-frontend）
   │              └─ /api|/admin|/resource → Gunicorn 127.0.0.1:8000
   ├─ :5173 → Nginx → 管理端静态（/var/www/epp/manager-5173）
   │              └─ 同上反代
   └─ :80/:443 → 已配置但公网不可用（备案/云侧限制）；证书仅备查
                          ▼
                   Django 5.1 + MySQL
```

| 组件 | 作用 |
|------|------|
| **Nginx** | 对外 8080/5173；静态资源 + API 反向代理 |
| **Gunicorn** | WSGI，2 worker，仅监听 `127.0.0.1:8000` |
| **systemd** | `epp-backend`、`nginx` 守护与开机自启 |
| **EPP-Configuration** | 配置中心，`link.sh` 软链到各子项目 |

### 1.2 与 dev 模式对比（勿混用）

| 维度 | Dev（本地调试） | 生产评审（当前） |
|------|----------------|------------------|
| 后端 | `manage.py runserver` | Gunicorn + `epp-backend.service` |
| 用户端 | `yarn dev` → webpack-dev-server :8080 | `yarn build` → Nginx :8080 静态 |
| 管理端 | `yarn dev` → Vite :5173 | `yarn build` → Nginx :5173 静态 |
| API 请求 | 常跨域直连 `:8000` | 同源，经 Nginx `/api` 反代 |
| 稳定性 | SSH 断开易挂 | systemd 自动重启 |

### 1.3 前端访问后端（已按 IP 配置）

- **用户端**：`VUE_APP_API_ROOT=http://114.116.202.158:8080/api`
- **管理端**：`VITE_API_BASE_URL=http://114.116.202.158:5173`，`VITE_BASE_PATH=/`
- **CORS**：`EPP_EXTRA_CORS_ORIGINS` 含 `:8080` 与 `:5173` 的 IP Origin
- **Cookie**：`EPP_SESSION_COOKIE_SECURE=false`（HTTP 评审；由 `settings.py` 读取 env）

### 1.4 外部依赖

| 功能 | 依赖 | 说明 |
|------|------|------|
| 深度研究 / 科研助手 | `RA_LLM_*`、Tavily 等 | 云端 API |
| 旧版 ChatGLM | `127.0.0.1:7861` | 可选 `ssh -R` |
| MinIO | `MINIO_*` | 占位密钥时降级 |
| MySQL | 本机 `EPP` 库 | 已配置 |

管理账号见 `EPP-Configuration/backend/development.env` 中 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（勿公开）。

---

## 2. 启动与停止

### 2.1 启动评审服务（推荐）

```bash
# 确保无 dev 进程占用端口
pkill -f 'manage.py runserver' || true
pkill -f 'webpack-dev-server' || true
pkill -f 'EPP-Frontend-Manager-Dev.*vite' || true

systemctl start epp-backend nginx
systemctl enable epp-backend nginx
```

### 2.2 停止评审服务

```bash
systemctl stop epp-backend nginx
```

### 2.3 一键更新（含构建）

```bash
cd /root/2026Spring-BUAA-SE-EPP_IID
git pull origin server    # 按实际分支
bash deploy.sh
```

---

## 3. 目录与配置

### 3.1 项目结构

```
/root/2026Spring-BUAA-SE-EPP_IID/
├── EPP-Backend-Dev/
├── EPP-Frontend-Dev/
├── EPP-Frontend-Manager-Dev/
├── EPP-Configuration/
├── deploy.sh
└── docs/DEPLOYMENT.md
```

### 3.2 静态资源

```
/var/www/epp/
├── user-frontend/     # Nginx :8080
└── manager-5173/      # Nginx :5173
```

### 3.3 关键配置（EPP-Configuration）

**`backend/development.env`**

```env
EPP_EXTRA_CORS_ORIGINS=http://114.116.202.158:8080,http://114.116.202.158:5173
EPP_SESSION_COOKIE_SECURE=false
```

**`frontend/user-frontend/prod.env.js`**

```js
VUE_APP_ROOT: '"http://114.116.202.158:8080"'
VUE_APP_API_ROOT: '"http://114.116.202.158:8080/api"'
```

**`frontend/manager-frontend/.env.production`**

```env
VITE_API_BASE_URL=http://114.116.202.158:5173
VITE_BASE_PATH=/
```

修改后：`bash EPP-Configuration/link.sh` → `yarn build`（两端）→ 复制到 `/var/www/epp/` → `systemctl restart epp-backend` → `systemctl reload nginx`。

**`backend/settings.py`**：`EPP_SESSION_COOKIE_SECURE` 从 env 读取；HTTP 评审必须为 `false`，否则登录 Session 无法写入。

### 3.4 系统级文件

| 文件 | 说明 |
|------|------|
| `/etc/nginx/conf.d/epp.conf` | :8080 / :5173 主站；:80/:443 保留备用 |
| `/etc/systemd/system/epp-backend.service` | Gunicorn |
| `/swapfile` | 2GB，防前端构建 OOM |

---

## 4. HTTPS / 域名（当前不可用）

- 课程组服务器**无法备案**，公网 **80/443** 及**无端口域名**访问不可作为评审入口。
- TrustAsia 证书与 `epp.conf` 中 443 配置仍保留在 `/etc/nginx/ssl/`，仅供将来云侧放行后启用。
- 域名 `eppmon2.asia` 解析可保留，但评审请统一使用 **IP + 端口**。

---

## 5. 服务管理

```bash
systemctl status epp-backend nginx mysqld
systemctl restart epp-backend
nginx -t && systemctl reload nginx
journalctl -u epp-backend -f
tail -f /var/log/nginx/error.log
```

### 仅更新前端

```bash
cd /root/2026Spring-BUAA-SE-EPP_IID
bash EPP-Configuration/link.sh

cd EPP-Frontend-Dev
NODE_OPTIONS='--max-old-space-size=2048' yarn run build
rm -rf /var/www/epp/user-frontend/* && cp -a dist/. /var/www/epp/user-frontend/

cd ../EPP-Frontend-Manager-Dev
yarn run build
rm -rf /var/www/epp/manager-5173/* && cp -a dist/. /var/www/epp/manager-5173/

systemctl reload nginx
```

---

## 6. 安全组

| 端口 | 用途 |
|------|------|
| **8080** | 用户端（评审主入口） |
| **5173** | 管理端（评审主入口） |
| 22 | SSH（建议限制来源 IP） |
| 80 / 443 | 当前不可用，无需依赖 |

---

## 7. 评审周：SSH 反向隧道（ChatGLM）

```bash
ssh -N -R 7861:127.0.0.1:7861 root@114.116.202.158
```

科研助手 / 深度研究不依赖此隧道。

---

## 8. 故障排查

| 现象 | 处理 |
|------|------|
| 8080/5173 无响应 | `systemctl status nginx`；是否被 `yarn dev` 占用端口 |
| 502 / API 失败 | `systemctl restart epp-backend`；`journalctl -u epp-backend -n 50` |
| 登录后立即退出 | 确认 `EPP_SESSION_COOKIE_SECURE=false` 且访问 **http://IP:端口** |
| 前端仍请求旧域名 | 检查 `prod.env.js` / `.env.production` 后重新 build 并部署静态 |
| 管理端白屏 | 确认 `VITE_BASE_PATH=/` 与 Nginx `root` 为 `manager-5173` |
| 与 dev 冲突 | 停掉 `runserver` 与两个 `yarn run dev` 后再启 systemd |

---

## 9. 部署检查清单

- [x] 配置中心改为公网 IP（8080/5173）
- [x] `EPP_SESSION_COOKIE_SECURE=false` 且 settings 读取 env
- [x] CORS 含 `:8080` 与 `:5173`
- [x] 前后端生产构建并发布至 `/var/www/epp/`
- [x] `epp-backend`、`nginx` 运行中
- [x] 无 `runserver` / `yarn dev` 占用评审端口
- [ ] 浏览器用 IP 完成登录与核心功能抽测

---

## 10. 维护提醒

- 勿将 `development.env`、`*.key` 提交公开仓库
- 课程结束后：轮换 API Key、修改 Admin 密码、视情况关闭公网访问
