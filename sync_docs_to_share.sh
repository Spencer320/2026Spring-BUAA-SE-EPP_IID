#!/usr/bin/env bash
# 将本仓库 docs 目录同步到 /mnt/f/LinuxShare/SE_work_docs
# 规则：同名目录合并（不清空、不删除目标侧多余文件/目录）；同名文件以 docs 为准覆盖。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DOCS="${SCRIPT_DIR}/docs"
DEST="/mnt/f/LinuxShare/SE_work_docs"

if [[ ! -d "$SRC_DOCS" ]]; then
  echo "错误: 源目录不存在: ${SRC_DOCS}" >&2
  exit 1
fi

mkdir -p "${DEST}"

rsync -a "${SRC_DOCS}/" "${DEST}/"

echo "已完成同步: ${SRC_DOCS} -> ${DEST}"
