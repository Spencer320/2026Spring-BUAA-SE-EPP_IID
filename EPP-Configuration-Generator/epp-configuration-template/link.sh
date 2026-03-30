#!/usr/bin/bash

root=$(realpath "$(dirname "$(realpath "$0")")/..")
echo "Root Directory is at $root"

# Frontend (User)
cd "$root/{core|path|frontend|user}/config"
ln -sf "../../EPP-Configuration/frontend/user-frontend/dev.env.js" "dev.env.js"
ln -sf "../../EPP-Configuration/frontend/user-frontend/prod.env.js" "prod.env.js"

# Frontend (Manager)
cd "$root/{core|path|frontend|manager}"
ln -sf "../EPP-Configuration/frontend/manager-frontend/.env.development" ".env.development"
ln -sf "../EPP-Configuration/frontend/manager-frontend/.env.production" ".env.production"

# Backend
cd "$root/{core|path|backend}"
ln -sf "../EPP-Configuration/backend/development.env" "development.env"
