# 获取脚本所在目录的父目录（即项目根目录）
$scriptDir = $PSScriptRoot
if (-not $scriptDir) {
    # 当脚本被点源执行时，使用另一种方式获取路径
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$root = Split-Path -Parent $scriptDir
Write-Host "Root Directory is at $root"

# 前端 (User) —— 对应原脚本的 Frontend (User) 部分
Push-Location "$root\EPP-Frontend-Dev\config"

# 强制创建符号链接 dev.env.js
$target = "dev.env.js"
$source = "..\..\EPP-Configuration\frontend\user-frontend\dev.env.js"
if (Test-Path $target) { Remove-Item $target -Force }
New-Item -ItemType SymbolicLink -Path $target -Target $source -Force | Out-Null

# 强制创建符号链接 prod.env.js
$target = "prod.env.js"
$source = "..\..\EPP-Configuration\frontend\user-frontend\prod.env.js"
if (Test-Path $target) { Remove-Item $target -Force }
New-Item -ItemType SymbolicLink -Path $target -Target $source -Force | Out-Null

Pop-Location

# 前端 (Manager) —— 对应原脚本的 Frontend (Manager) 部分
Push-Location "$root\EPP-Frontend-Manager-Dev"

$target = ".env.development"
$source = "..\EPP-Configuration\frontend\manager-frontend\.env.development"
if (Test-Path $target) { Remove-Item $target -Force }
New-Item -ItemType SymbolicLink -Path $target -Target $source -Force | Out-Null

$target = ".env.production"
$source = "..\EPP-Configuration\frontend\manager-frontend\.env.production"
if (Test-Path $target) { Remove-Item $target -Force }
New-Item -ItemType SymbolicLink -Path $target -Target $source -Force | Out-Null

Pop-Location

# 后端 (Backend) —— 对应原脚本的 Backend 部分
Push-Location "$root\EPP-Backend-Dev"

$target = "development.env"
$source = "..\EPP-Configuration\backend\development.env"
if (Test-Path $target) { Remove-Item $target -Force }
New-Item -ItemType SymbolicLink -Path $target -Target $source -Force | Out-Null

Pop-Location