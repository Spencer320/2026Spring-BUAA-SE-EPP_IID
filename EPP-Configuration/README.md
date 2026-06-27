# EPP-Configuration

各子项目共享的环境配置。仓库内仅提交 **模板文件**（`*.template`），真实密钥与本地覆盖值不入库。

## 首次配置

在 mono-repo 根目录执行：

```bash
cd EPP-Configuration
bash link.sh
```

脚本会：

1. 若本地配置不存在，从 `*.template` 复制生成实际配置文件
2. 在 `EPP-Backend-Dev`、`EPP-Frontend-Dev`、`EPP-Frontend-Manager-Dev` 中建立指向本目录的软链接

生成后请编辑 `backend/development.env`，填入有效的 API Key 与密钥。

## 目录结构

```
EPP-Configuration/
├── link.sh
├── backend/
│   ├── development.env.template   # 提交到 Git
│   └── development.env            # 本地实际配置（gitignore）
└── frontend/
    ├── user-frontend/
    │   ├── dev.env.js.template
    │   ├── prod.env.js.template
    │   ├── dev.env.js
    │   └── prod.env.js
    └── manager-frontend/
        ├── .env.development.template
        ├── .env.production.template
        ├── .env.development
        └── .env.production
```

## 修改配置

1. 在 `EPP-Configuration` 下编辑对应的**实际配置文件**（非 `.template`）
2. 若需同步给团队，更新对应的 `*.template`（使用占位符，勿提交真实密钥）
3. 子项目通过软链接自动读取，无需额外复制

## 新增配置项

新增环境变量时：

1. 在 `backend/development.env.template` 添加占位项与注释
2. 在 `EPP-Backend-Dev/backend/settings.py` 或对应前端配置中读取
3. 更新对应子项目 README 的「关键配置项」章节
