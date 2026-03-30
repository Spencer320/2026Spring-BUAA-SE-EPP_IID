# EPP 前后端配置中心

此仓库可能包含敏感信息（如 API 密钥等），课程结束后也最好不要公开。

所有项目的配置文件存放于此仓库，使用时，通过符号链接链接入各个仓库。

以后端为例，具体如下。源路径（`-s` 后第一个参数）建议使用绝对路径，除非你比较清楚相对路径的起点。

```bash
cd path/to/epp-backend
ln -s path/to/this/repo/backend/development.env development.env
```

> Windows 下，可使用 `mklink` 代替，具体参数可以查询一下。
>
> 其实直接复制过去也行，就是要注意同步，并且不要把配置文件提交到其他仓库。

下文将描述各个仓库的配置文件，部分还没有出现在此，暂时用不到。同时部分配置项残缺，后续会随着开发进度补齐。

## 后端配置 EPP-Backend

包含一项内容：`backend/development.env`，链接到后端根目录（与 `manage.py` 平级）。

## 前端配置

### 用户前端 EPP-Frontend

包含两项内容：`frontend/user-frontend/dev.env.js` 以及 `frontend/user-frontend/prod.env.js`，链接到前端 `config` 目录下。

### 管理员前端 EPP-Frontend-Manager

包含两项内容：`frontend/manager-frontend/.env.development` 以及 `frontend/manager-frontend/.env.product`，链接到前端根目录（与 `node_modules` 平级）。
