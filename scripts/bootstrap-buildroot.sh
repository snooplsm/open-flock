#!/usr/bin/env sh
set -eu

BR_VERSION="2025.02.2"
ROOT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
BR_DIR="$ROOT_DIR/third_party/buildroot"
EXT_DIR="$ROOT_DIR/buildroot-external"
OUT_DIR="$ROOT_DIR/out/picam-rpi4"

mkdir -p "$ROOT_DIR/third_party" "$ROOT_DIR/out"

if [ ! -d "$BR_DIR" ]; then
    git clone --depth 1 --branch "$BR_VERSION" https://github.com/buildroot/buildroot.git "$BR_DIR"
fi

make -C "$BR_DIR" BR2_EXTERNAL="$EXT_DIR" O="$OUT_DIR" picam_rpi4_defconfig

echo
echo "Config ready at: $OUT_DIR/.config"
echo "Run: make -C $BR_DIR BR2_EXTERNAL=$EXT_DIR O=$OUT_DIR -j\$(nproc)"
