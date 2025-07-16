#!/usr/bin/env bash
set -euo pipefail

# プロジェクトルートを基準に
ROOT="$(pwd)"
TARGET="$ROOT/s_bench"

# 1) s_bench ルートと、モジュール用サブディレクトリ群を作成
declare -a MODULES=(
  cpu_load
  gpu_load
  system_info
  storage_load
  sound_test
  network_test
  util
)

echo "=== Creating s_bench and subdirectories ==="
mkdir -p "$TARGET"
for m in "${MODULES[@]}"; do
  mkdir -p "$TARGET/$m"
  echo "  - ensured: s_bench/$m"
done

# 2) 各モジュールのコンテンツを移動
echo
echo "=== Moving files into s_bench/... ==="
for m in "${MODULES[@]}"; do
  SRC="$ROOT/$m"
  DST="$TARGET/$m"
  if [ -d "$SRC" ]; then
    echo "  Moving contents of $m/ → s_bench/$m/"
    mv "$SRC"/* "$DST"/
    # 空になった元ディレクトリを削除（失敗しても無視）
    rmdir "$SRC" 2>/dev/null || true
  fi
done

# 3) ルート直下の main.py を s_bench/ へ移動
if [ -f "$ROOT/main.py" ]; then
  echo "  Moving main.py → s_bench/"
  mv "$ROOT/main.py" "$TARGET/"
fi

# 4) ついでに、必要なら混在ファイルも追加で mv してください
#    例: mv "$ROOT"/mixed_load/* "$TARGET/cpu_load"/
#         mv "$ROOT"/gpu_load_cuda.py "$TARGET/gpu_load"/
#         mv "$ROOT"/gpu_load_rocm.py "$TARGET/gpu_load"/
#         mv "$ROOT"/texture.jpg "$TARGET/gpu_load"/
#         mv "$ROOT"/nettest_config.json "$TARGET/network_test"/

# 5) __init__.py を自動生成
echo
echo "=== Creating __init__.py in each package ==="
for m in "${MODULES[@]}"; do
  INIT="$TARGET/$m/__init__.py"
  if [ ! -f "$INIT" ]; then
    touch "$INIT"
    echo "  Created $INIT"
  else
    echo "  Exists      $INIT"
  fi
done

echo
echo "=== Done! ==="
echo "Your directory tree under s_bench/ is now ready for Python imports."
