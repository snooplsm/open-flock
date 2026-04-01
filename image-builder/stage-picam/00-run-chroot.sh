#!/bin/bash -e

# Networking is intentionally left unconfigured here.
# Configure Wi-Fi and IP settings at first boot with Raspberry Pi Imager
# or your own provisioning system.

# ONNX Runtime preload
ONNX_VERSION="1.18.1"
ONNX_ARCHIVE="onnxruntime-linux-aarch64-${ONNX_VERSION}.tgz"
ONNX_URL="https://github.com/microsoft/onnxruntime/releases/download/v${ONNX_VERSION}/${ONNX_ARCHIVE}"
ONNX_ROOT="/opt/onnxruntime"

mkdir -p /tmp/onnxdl "${ONNX_ROOT}/${ONNX_VERSION}"
curl -fL "${ONNX_URL}" -o "/tmp/onnxdl/${ONNX_ARCHIVE}"
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

# Optional TFLite package (repo-dependent)
if apt-cache show libtensorflow-lite-dev >/dev/null 2>&1; then
  apt-get install -y libtensorflow-lite-dev
fi

# Enable lighttpd at boot
systemctl enable lighttpd || true
