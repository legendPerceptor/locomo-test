#!/bin/bash
set -euo pipefail

OPENCLAW_HOME_DIR="/home/yuanjian/Development/memory-projects/openclaw_dir"
AGFS_DATA_DIR="/home/yuanjian/Development/memory-projects/agfs_data"

docker stop ogmem_yuanjian openclaw_ogmem_yuanjian 2>/dev/null || true

rm -rf "$OPENCLAW_HOME_DIR/agents/main/sessions/"*
rm -rf "$OPENCLAW_HOME_DIR/agents/main/archive/"*
rm -rf "$OPENCLAW_HOME_DIR/agents/main/agent/"*
rm -rf "$OPENCLAW_HOME_DIR/tasks/"*
rm -rf "$OPENCLAW_HOME_DIR/logs/"*
rm -rf "$AGFS_DATA_DIR/"*
rm -rf test_results/ogmem-small 2>/dev/null || true

docker start ogmem_yuanjian openclaw_ogmem_yuanjian