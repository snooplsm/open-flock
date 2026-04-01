#!/usr/bin/env bash
set -euo pipefail

# Raspberry Pi OS Lite provisioner
# - Optionally configures Wi-Fi/static IP from user env vars
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

# Optional network config (no hardcoded credentials in repo)
WIFI_ENABLE="${WIFI_ENABLE:-}"
WIFI_COUNTRY="${WIFI_COUNTRY:-US}"
WIFI_SSID="${WIFI_SSID:-}"
WIFI_PSK="${WIFI_PSK:-}"
WIFI_SECONDARY_SSID="${WIFI_SECONDARY_SSID:-}"
WIFI_SECONDARY_PSK="${WIFI_SECONDARY_PSK:-$WIFI_PSK}"
STATIC_IP_CIDR="${STATIC_IP_CIDR:-}"   # e.g. 192.168.50.24/24
ROUTER_IP="${ROUTER_IP:-}"             # e.g. 192.168.50.1
DNS_SERVERS="${DNS_SERVERS:-}"

if [[ -z "${WIFI_ENABLE}" ]]; then
  if [[ -n "${WIFI_SSID}" && -n "${WIFI_PSK}" ]]; then
    WIFI_ENABLE=1
  else
    WIFI_ENABLE=0
  fi
fi

log() {
  printf '[rpi-lite] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

configure_wifi() {
  if [[ "${WIFI_ENABLE}" != "1" ]]; then
    log "Wi-Fi config skipped (WIFI_ENABLE=${WIFI_ENABLE})"
    return
  fi
  if [[ -z "${WIFI_SSID}" || -z "${WIFI_PSK}" ]]; then
    echo "WIFI_ENABLE=1 requires WIFI_SSID and WIFI_PSK"
    exit 1
  fi

  log "Configuring /etc/wpa_supplicant/wpa_supplicant.conf from env vars"
  install -d -m 0755 /etc/wpa_supplicant
  cat > /etc/wpa_supplicant/wpa_supplicant.conf <<WPA
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=${WIFI_COUNTRY}

network={
    ssid="${WIFI_SSID}"
    psk="${WIFI_PSK}"
    scan_ssid=1
    priority=20
}
WPA

  if [[ -n "${WIFI_SECONDARY_SSID}" && -n "${WIFI_SECONDARY_PSK}" ]]; then
    cat >> /etc/wpa_supplicant/wpa_supplicant.conf <<WPA2

network={
    ssid="${WIFI_SECONDARY_SSID}"
    psk="${WIFI_SECONDARY_PSK}"
    scan_ssid=1
    priority=10
}
WPA2
  fi
  chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf
}

configure_static_ip() {
  if [[ -z "${STATIC_IP_CIDR}" ]]; then
    log "Static IP config skipped (STATIC_IP_CIDR not set)"
    return
  fi
  if [[ -z "${ROUTER_IP}" ]]; then
    echo "STATIC_IP_CIDR requires ROUTER_IP"
    exit 1
  fi

  log "Configuring static wlan0 IP in /etc/dhcpcd.conf"
  cp -a /etc/dhcpcd.conf /etc/dhcpcd.conf.bak.$(date +%s)

  awk '
    BEGIN {skip=0}
    /^interface wlan0$/ {skip=1; next}
    skip==1 && /^\s*$/ {skip=0; next}
    skip==1 {next}
    {print}
  ' /etc/dhcpcd.conf > /etc/dhcpcd.conf.new

  cat >> /etc/dhcpcd.conf.new <<DHCPCD

interface wlan0
static ip_address=${STATIC_IP_CIDR}
static routers=${ROUTER_IP}
DHCPCD

  if [[ -n "${DNS_SERVERS}" ]]; then
    cat >> /etc/dhcpcd.conf.new <<DHCPCD2
static domain_name_servers=${DNS_SERVERS}
DHCPCD2
  fi

  mv /etc/dhcpcd.conf.new /etc/dhcpcd.conf
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

restart_network() {
  if [[ "${WIFI_ENABLE}" != "1" && -z "${STATIC_IP_CIDR}" ]]; then
    return
  fi
  log "Restarting network services"
  systemctl restart dhcpcd || true
  systemctl restart wpa_supplicant || true
}

summary() {
  cat <<OUT

Provisioning complete.

Configured:
- Wi-Fi enabled: ${WIFI_ENABLE}
- Wi-Fi SSID: ${WIFI_SSID:-<not set>}
- Wi-Fi secondary SSID: ${WIFI_SECONDARY_SSID:-<not set>}
- Static IP CIDR: ${STATIC_IP_CIDR:-<dhcp>}
- Router: ${ROUTER_IP:-<dhcp>}
- DNS: ${DNS_SERVERS:-<system default>}

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
  configure_wifi
  configure_static_ip
  install_onnxruntime
  install_tflite
  restart_network
  summary
}

main "$@"
