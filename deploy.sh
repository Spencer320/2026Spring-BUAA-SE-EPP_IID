#!/usr/bin/env bash
# 课程评审环境一键更新（git pull → migrate → 构建前端 → 重启服务）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "==> 同步配置链接"
bash EPP-Configuration/link.sh

echo "==> 后端迁移"
cd EPP-Backend-Dev
.venv/bin/python manage.py migrate --noinput

echo "==> 构建用户端"
cd "$ROOT/EPP-Frontend-Dev"
yarn install --network-timeout 600000
yarn run build
rm -rf /var/www/epp/user-frontend/*
cp -a dist/. /var/www/epp/user-frontend/

echo "==> 构建管理端"
cd "$ROOT/EPP-Frontend-Manager-Dev"
yarn install --network-timeout 600000
yarn run build
rm -rf /var/www/epp/manager-5173/*
mkdir -p /var/www/epp/manager-5173
cp -a dist/. /var/www/epp/manager-5173/

echo "==> 重启服务"
systemctl restart epp-backend
nginx -t && systemctl reload nginx

echo "Deploy OK"
echo "  用户端: http://114.116.202.158:8080/"
echo "  管理端: http://114.116.202.158:5173/"
echo "  API:    经 8080/5173 同端口 /api/..."
