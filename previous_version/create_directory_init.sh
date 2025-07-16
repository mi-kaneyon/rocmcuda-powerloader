#!/bin/bash
# setup.sh
# GitHub クローン後に必要なサブディレクトリと __init__.py を作成するスクリプト

# 作成するサブディレクトリのリスト
dirs=(
  "s_bench/cpu_load"
  "s_bench/gpu_load"
  "s_bench/old_version"
  "s_bench/sound_test"
  "s_bench/storage_load"
  "s_bench/system_info"
  "s_bench/network_test"
)

echo "必要なディレクトリを作成します..."

for dir in "${dirs[@]}"; do
  mkdir -p "$dir"
  echo "Directory created or exists: $dir"
  init_file="$dir/__init__.py"
  if [ ! -f "$init_file" ]; then
    echo "# This file makes this directory a Python package." > "$init_file"
    echo "__init__.py created in $dir"
  else
    echo "__init__.py already exists in $dir"
  fi
done

echo "すべてのサブディレクトリと __init__.py の設定が完了しました。"
