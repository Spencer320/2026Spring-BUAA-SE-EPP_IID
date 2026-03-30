# EPP 配置中心（EPP-Configuration）

本仓库用于统一管理 EPP 各子项目的配置模板（后端、用户前端、管理前端）。  
运行时通过**符号链接**把本地真实配置挂载到对应项目目录，避免多仓库重复维护同一份配置。

## 1. 仓库职责

- 集中存放环境配置模板（可提交）
- 通过软链接向各子项目“分发”配置
- 作为配置变更的唯一来源（single source of truth）

> 当前策略：模板入库，真实值本地覆盖。  
> 真实配置文件已在 `EPP-Configuration/.gitignore` 中忽略，不应提交。

## 2. 配置文件映射关系

模板与真实文件的映射关系如下：

- 后端 `EPP-Backend-Dev`
  - 模板：`backend/development.env.example`
  - 本地真实文件（忽略）：`backend/development.env`
  - 目标路径：`EPP-Backend-Dev/development.env`（与 `manage.py` 同级）
- 用户前端 `EPP-Frontend-Dev`
  - 模板：`frontend/user-frontend/dev.env.js.example`
  - 本地真实文件（忽略）：`frontend/user-frontend/dev.env.js`
  - 目标路径：`EPP-Frontend-Dev/config/dev.env.js`
  - 模板：`frontend/user-frontend/prod.env.js.example`
  - 本地真实文件（忽略）：`frontend/user-frontend/prod.env.js`
  - 目标路径：`EPP-Frontend-Dev/config/prod.env.js`
- 管理前端 `EPP-Frontend-Manager-Dev`
  - 模板：`frontend/manager-frontend/.env.development.example`
  - 本地真实文件（忽略）：`frontend/manager-frontend/.env.development`
  - 目标路径：`EPP-Frontend-Manager-Dev/.env.development`
  - 模板：`frontend/manager-frontend/.env.production.example`
  - 本地真实文件（忽略）：`frontend/manager-frontend/.env.production`
  - 目标路径：`EPP-Frontend-Manager-Dev/.env.production`

## 3. 首次使用（先从模板生成本地真实配置）

在 `EPP-Configuration` 目录执行：

```bash
cp backend/development.env.example backend/development.env
cp frontend/user-frontend/dev.env.js.example frontend/user-frontend/dev.env.js
cp frontend/user-frontend/prod.env.js.example frontend/user-frontend/prod.env.js
cp frontend/manager-frontend/.env.development.example frontend/manager-frontend/.env.development
cp frontend/manager-frontend/.env.production.example frontend/manager-frontend/.env.production
```

然后按本机环境填写真实值（API Key、密码、域名等）。

## 4. Linux / macOS 启动方式（推荐）

在 mono-repo 根目录下执行（替换为实际路径）：

```bash
cd /home/Spencer/projects/SE_project/EPP-Configuration
bash link.sh
```

脚本会自动创建或覆盖上述所有软链接（使用 `ln -sf`）。

## 5. Windows 启动方式（使用 `mklink`）

在 **管理员权限** 的 `cmd` 中执行（替换为实际路径）：

```bat
cd /d D:\projects\SE_project

mklink "EPP-Backend-Dev\development.env" "EPP-Configuration\backend\development.env"

mklink "EPP-Frontend-Dev\config\dev.env.js" "EPP-Configuration\frontend\user-frontend\dev.env.js"
mklink "EPP-Frontend-Dev\config\prod.env.js" "EPP-Configuration\frontend\user-frontend\prod.env.js"

mklink "EPP-Frontend-Manager-Dev\.env.development" "EPP-Configuration\frontend\manager-frontend\.env.development"
mklink "EPP-Frontend-Manager-Dev\.env.production" "EPP-Configuration\frontend\manager-frontend\.env.production"
```

说明：

- 以上命令创建的是**文件符号链接**（不需要 `/D`，`/D` 仅用于目录链接）。
- 若提示权限不足，请确认使用“以管理员身份运行”。
- 若目标文件已存在，需先删除目标文件再执行 `mklink`。

## 6. 故障排查

- `link.sh` 后配置未生效：
  - 检查目标路径是否是链接（而不是普通文件）
  - 检查链接是否指向本仓库当前分支下的正确文件
- 前端/后端仍读到旧配置：
  - 先删除旧文件，再重新执行 `link.sh`（或重新执行 `mklink`）
  - 重启后端/前端开发服务

