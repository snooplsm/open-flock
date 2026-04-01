#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
PIGEN_DIR="${ROOT_DIR}/third_party/pi-gen"
WORK_DIR="${ROOT_DIR}/out/pi-gen"
DEPLOY_DIR="${WORK_DIR}/deploy"
STAGE_SRC="${ROOT_DIR}/image-builder/stage-picam"

PIGEN_REF="${PIGEN_REF:-bookworm}"
IMG_NAME="${IMG_NAME:-picam-rpios-lite}"
LOCALE_DEFAULT="${LOCALE_DEFAULT:-en_US.UTF-8}"
TARGET_HOSTNAME="${TARGET_HOSTNAME:-picam}"
TARGET_USER="${TARGET_USER:-pi}"
TARGET_PASS="${TARGET_PASS:-raspberry}"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required"
  exit 1
fi

if [ "$(uname -s)" != "Linux" ]; then
  cat <<MSG
pi-gen image builds are not reliable on non-Linux hosts (macOS/Windows Docker),
and often fail with setarch/qemu/rootfs bootstrap errors.

Recommended path on this machine:
1) Flash stock Raspberry Pi OS Lite with Raspberry Pi Imager
2) Boot the Pi
3) Run: sudo ./scripts/rpi-lite-provision.sh

If you still want custom image builds, run this script on a native Linux host/VM.
MSG
  exit 2
fi

mkdir -p "${ROOT_DIR}/third_party" "${WORK_DIR}"

if [ ! -d "${PIGEN_DIR}" ]; then
  git clone https://github.com/RPi-Distro/pi-gen.git "${PIGEN_DIR}"
fi

(
  cd "${PIGEN_DIR}"
  git fetch --all --tags
  git checkout "${PIGEN_REF}"
)

rm -rf "${PIGEN_DIR}/stage-picam"
cp -a "${STAGE_SRC}" "${PIGEN_DIR}/stage-picam"

cat > "${PIGEN_DIR}/config" <<CFG
IMG_NAME='${IMG_NAME}'
RELEASE='bookworm'
ENABLE_SSH=1
TARGET_HOSTNAME='${TARGET_HOSTNAME}'
FIRST_USER_NAME='${TARGET_USER}'
FIRST_USER_PASS='${TARGET_PASS}'
LOCALE_DEFAULT='${LOCALE_DEFAULT}'
STAGE_LIST='stage0 stage1 stage2 stage-picam'
DEPLOY_COMPRESSION='xz'
CFG

mkdir -p "${DEPLOY_DIR}"

(
  cd "${PIGEN_DIR}"
  export WORK_DIR
  export DEPLOY_DIR
  ./build-docker.sh
)

echo
echo "Image build complete. Outputs in: ${DEPLOY_DIR}"
ls -lh "${DEPLOY_DIR}" || true
