#!/usr/bin/env bash
set -euo pipefail

# Raspberry Pi OS Lite provisioner
# - Leaves network configuration to OS/imager/admin
# - Installs ONNX Runtime (C/C++ prebuilt)
# - Installs TensorFlow Lite dev package (if available)
# - Installs python3-picamera2, ffmpeg, and lighttpd
#
# Run on the Pi as root:
#   sudo ./scripts/rpi-lite-provision.sh

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

ONNX_VERSION="${ONNX_VERSION:-1.18.1}"
ONNX_ARCHIVE="onnxruntime-linux-aarch64-${ONNX_VERSION}.tgz"
ONNX_URL="https://github.com/microsoft/onnxruntime/releases/download/v${ONNX_VERSION}/${ONNX_ARCHIVE}"
ONNX_ROOT="/opt/onnxruntime"

log() {
  printf '[rpi-lite] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

install_base_packages() {
  log "Installing base packages"
  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    build-essential \
    cmake \
    pkg-config \
    unzip \
    libatomic1
}

install_media_packages() {
  log "Installing media stack packages"
  apt-get install -y --no-install-recommends \
    python3-picamera2 \
    ffmpeg \
    lighttpd

  systemctl enable lighttpd || true
  systemctl restart lighttpd || true
}

install_onnxruntime() {
  log "Installing ONNX Runtime ${ONNX_VERSION} (aarch64 prebuilt)"
  require_cmd curl
  require_cmd tar

  install -d -m 0755 /tmp/onnxdl "${ONNX_ROOT}"
  curl -fL "${ONNX_URL}" -o "/tmp/onnxdl/${ONNX_ARCHIVE}"

  rm -rf "${ONNX_ROOT}/${ONNX_VERSION}"
  mkdir -p "${ONNX_ROOT}/${ONNX_VERSION}"
  tar -xzf "/tmp/onnxdl/${ONNX_ARCHIVE}" -C "${ONNX_ROOT}/${ONNX_VERSION}" --strip-components=1

  ln -sfn "${ONNX_ROOT}/${ONNX_VERSION}" "${ONNX_ROOT}/current"

  cat > /etc/ld.so.conf.d/onnxruntime.conf <<LDSO
${ONNX_ROOT}/current/lib
LDSO
  ldconfig

  cat > /etc/profile.d/onnxruntime.sh <<ENV
export ONNXRUNTIME_ROOT=${ONNX_ROOT}/current
export CPLUS_INCLUDE_PATH=\$ONNXRUNTIME_ROOT/include:\${CPLUS_INCLUDE_PATH:-}
export LIBRARY_PATH=\$ONNXRUNTIME_ROOT/lib:\${LIBRARY_PATH:-}
export LD_LIBRARY_PATH=\$ONNXRUNTIME_ROOT/lib:\${LD_LIBRARY_PATH:-}
ENV
  chmod 0644 /etc/profile.d/onnxruntime.sh
}

install_tflite() {
  log "Installing TensorFlow Lite development package"

  if apt-cache show libtensorflow-lite-dev >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends libtensorflow-lite-dev
    return
  fi

  log "libtensorflow-lite-dev not found in apt sources."
  log "TFLite install skipped. Enable bookworm repos with that package or build from source manually."
}

summary() {
  cat <<OUT

Provisioning complete.

Configured:
- Networking: unchanged (configure via Raspberry Pi Imager or system settings)

Installed:
- ONNX Runtime: ${ONNX_ROOT}/current
- TensorFlow Lite: apt package if available
- Camera/stream/web: python3-picamera2, ffmpeg, lighttpd

Next checks:
- ldconfig -p | grep -E 'onnxruntime|tensorflowlite'
- systemctl status lighttpd --no-pager
OUT
}

main() {
  install_base_packages
  install_media_packages
  install_onnxruntime
  install_tflite
  summary
}

main "$@"
