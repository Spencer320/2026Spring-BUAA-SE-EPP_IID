#!/usr/bin/env bash
# 从模板生成本地配置（若不存在），并在各子项目中建立软链接。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

bootstrap_from_template() {
  local template="$1"
  local target="$2"
  if [[ ! -e "$target" && -f "$template" ]]; then
    cp "$template" "$target"
    echo "[created] $target (from template — please edit secrets before use)"
  fi
}

link_file() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  ln -sfn "$src" "$dest"
  echo "[linked] $dest -> $src"
}

echo "==> EPP-Configuration: bootstrap local configs"
bootstrap_from_template "$SCRIPT_DIR/backend/development.env.template" "$SCRIPT_DIR/backend/development.env"
bootstrap_from_template "$SCRIPT_DIR/frontend/user-frontend/dev.env.js.template" "$SCRIPT_DIR/frontend/user-frontend/dev.env.js"
bootstrap_from_template "$SCRIPT_DIR/frontend/user-frontend/prod.env.js.template" "$SCRIPT_DIR/frontend/user-frontend/prod.env.js"
bootstrap_from_template "$SCRIPT_DIR/frontend/manager-frontend/.env.development.template" "$SCRIPT_DIR/frontend/manager-frontend/.env.development"
bootstrap_from_template "$SCRIPT_DIR/frontend/manager-frontend/.env.production.template" "$SCRIPT_DIR/frontend/manager-frontend/.env.production"

echo "==> EPP-Configuration: link into subprojects"
link_file "$SCRIPT_DIR/backend/development.env" "$ROOT_DIR/EPP-Backend-Dev/development.env"
link_file "$SCRIPT_DIR/frontend/user-frontend/dev.env.js" "$ROOT_DIR/EPP-Frontend-Dev/config/dev.env.js"
link_file "$SCRIPT_DIR/frontend/user-frontend/prod.env.js" "$ROOT_DIR/EPP-Frontend-Dev/config/prod.env.js"
link_file "$SCRIPT_DIR/frontend/manager-frontend/.env.development" "$ROOT_DIR/EPP-Frontend-Manager-Dev/.env.development"
link_file "$SCRIPT_DIR/frontend/manager-frontend/.env.production" "$ROOT_DIR/EPP-Frontend-Manager-Dev/.env.production"

echo "Done."
