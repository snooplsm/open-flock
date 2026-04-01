#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
IMAGE_NAME="picam-buildroot:latest"
CACHE_VOLUME="${CACHE_VOLUME:-picam-buildroot-cache}"
CONTAINER_OUT="/cache/picam-rpi4"
JOBS="${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || echo 8)}"
CLEAN="${CLEAN:-0}"
LOG_PATH="/work/out/picam-rpi4/build.log"

cd "$ROOT_DIR"

docker build -t "$IMAGE_NAME" -f docker/buildroot/Dockerfile .

docker run --rm -it \
  -v "$ROOT_DIR":/work \
  -v "$CACHE_VOLUME":/cache \
  -w /work \
  "$IMAGE_NAME" \
  bash -lc '
    set -eu
    if [ ! -d /work/third_party/buildroot ]; then
      git clone --depth 1 --branch "2025.02.2" https://github.com/buildroot/buildroot.git /work/third_party/buildroot
    fi
    if [ "'"$CLEAN"'" = "1" ]; then
      rm -rf "'"$CONTAINER_OUT"'"
    fi
    make -C third_party/buildroot BR2_EXTERNAL=/work/buildroot-external O="'"$CONTAINER_OUT"'" picam_rpi4_defconfig
    mkdir -p /work/out/picam-rpi4
    if ! make -C third_party/buildroot BR2_EXTERNAL=/work/buildroot-external O="'"$CONTAINER_OUT"'" -j"'"$JOBS"'" 2>&1 | tee "'"$LOG_PATH"'"; then
      echo
      echo "Build failed. Showing last 120 lines with error markers:"
      tail -n 120 "'"$LOG_PATH"'" | sed -n "/error\\|Error\\|No such file\\|undefined reference/p"
      echo
      echo "Full log: '"$LOG_PATH"'"
      exit 1
    fi
    rm -rf /work/out/picam-rpi4/images
    cp -a "'"$CONTAINER_OUT"'/images" /work/out/picam-rpi4/
  '
