# Open Flock (Raspberry Pi 4)

Goal: build a mobile flock camera platform that can run on Raspberry Pi in the field, stream live video, and perform on-device plate OCR/GPS capture.

Primary app runtime docs live in [`server/README.md`](/Users/snooplsm/picam/server/README.md).

Buildroot-based minimal OS that boots a camera pipeline and HTTP endpoint with no Python runtime.

## What this provides

- Buildroot external tree for **Raspberry Pi 4 (64-bit)**
- `libcamera` package enabled in image
- `libcamera` V4L2 compatibility is enabled (`BR2_PACKAGE_LIBCAMERA_V4L2_COMPAT`)
- ONNX Runtime C/C++ runtime (`picam-onnxruntime`, vendored-deps build path)
- TensorFlow Lite C/C++ runtime (`BR2_PACKAGE_TENSORFLOW_LITE`)
- Custom **C** camera pipeline (`picam-pipeline`) using V4L2 capture (`/dev/video0`)
- Custom **C** HTTP server (`picam-httpd`) with:
  - `GET /health`
  - `GET /latest.jpg`
- Wi-Fi connectivity via `wpa_supplicant`
- BLE stack via `bluez5` tools
- BusyBox init startup script that auto-launches stack

## Repo layout

- `buildroot-external/configs/picam_rpi4_defconfig` - main Buildroot config
- `buildroot-external/board/picam/config.txt` - Raspberry Pi firmware camera/boot config
- `buildroot-external/board/picam/cmdline.txt` - kernel cmdline tuned for fast startup
- `buildroot-external/board/picam/overlay/etc/init.d/S40picam-stack` - boot service
- `buildroot-external/package/picam-onnxruntime/` - ONNX Runtime package recipe
- `buildroot-external/package/picam-pipeline/src/picam_pipeline.c` - camera pipeline
- `buildroot-external/package/picam-httpd/src/picam_httpd.c` - HTTP server
- `scripts/bootstrap-buildroot.sh` - fetch Buildroot + initialize out dir

## Build

1. Bootstrap Buildroot and generate config:

```sh
./scripts/bootstrap-buildroot.sh
```

2. Build image:

```sh
make -C third_party/buildroot BR2_EXTERNAL=$PWD/buildroot-external O=$PWD/out/picam-rpi4 -j$(nproc)
```

3. Write image artifacts to SD card (from `out/picam-rpi4/images`).

## Build with Docker

If you prefer a fully containerized toolchain:

```sh
./scripts/docker-build.sh
```

This builds a `picam-buildroot:latest` image and runs the full Buildroot build inside the container.
The build now happens in a persistent Docker volume (`/cache`) and copies final images back to `out/picam-rpi4/images` to avoid macOS bind-mount permission issues.

If you already hit a permission error, clean stale output once:

```sh
rm -rf out/picam-rpi4
```

Incremental build notes:

- Build cache is persisted in Docker volume `picam-buildroot-cache`.
- Subsequent runs should be much faster than first compile.
- Force a clean rebuild only when needed:

```sh
CLEAN=1 ./scripts/docker-build.sh
```

- Tune parallelism:

```sh
JOBS=12 ./scripts/docker-build.sh
```

## Raspberry Pi OS Lite Path

If you want to use stock Raspberry Pi OS Lite instead of Buildroot, use:

```sh
sudo ./scripts/rpi-lite-provision.sh
```

This script:

- Leaves Wi-Fi/IP configuration unchanged (configure per-device)

It also installs:

- ONNX Runtime C/C++ prebuilt in `/opt/onnxruntime/current`
- TensorFlow Lite dev package from apt when available (`libtensorflow-lite-dev`)
- `python3-picamera2`, `ffmpeg`, and `lighttpd` (enabled at boot)

No Wi-Fi credentials or static IP are stored in this repo.

## Build Flashable Pi OS Lite Image

To build a reusable Raspberry Pi OS Lite image that already includes your defaults, use:

```sh
./scripts/build-rpi-lite-image.sh
```

What this image includes:

- No embedded Wi-Fi credentials or static IP defaults
- ONNX Runtime preloaded under `/opt/onnxruntime/current`
- TFLite dev package install attempt (`libtensorflow-lite-dev`) when available
- `python3-picamera2`, `ffmpeg`, `lighttpd` (enabled)

Output images are written to:

- `out/pi-gen/deploy`

Notes:

- Build uses `pi-gen` inside Docker and can take a while.
- Default first user/password in the image builder script is `pi` / `raspberry`; change before production use.
- `pi-gen` builds are intended for native Linux hosts; on macOS Docker they commonly fail (`setarch`, rootfs bootstrap).

## Reliable Multi-Pi Rollout (Recommended On macOS)

1. Flash stock Raspberry Pi OS Lite to SD cards with Raspberry Pi Imager.
2. In Imager advanced options, set SSH and network for your environment.
3. After first boot on each Pi, run:

```sh
sudo ./scripts/rpi-lite-provision.sh
```

This gives you the same practical outcome without fragile pi-gen builds on macOS.

## First boot

1. Configure network on the device (or via Imager provisioning).
2. Boot Pi 4 with Raspberry Pi Camera attached.
3. Find IP and test:

```sh
curl http://<pi-ip>:8080/health
curl -o frame.jpg http://<pi-ip>:8080/latest.jpg
```

## BLE enablement

At boot, stack runs:

- `hciconfig hci0 up`
- `btmgmt le on`

For custom GATT services, add a dedicated C daemon using BlueZ D-Bus APIs and launch it from `S40picam-stack`.

## Startup time target (<5s)

This scaffold is designed for fast boot, but sub-5s depends on SD card, kernel, and service scope.

Recommended tuning:

- Keep BusyBox init (no systemd)
- Remove non-essential packages and shell utilities
- Use static networking when possible (skip DHCP wait)
- Keep camera pipeline at fixed format/resolution
- Disable extra console/getty services
- Use high-performance SD card (A2/U3)
- Tune kernel cmdline for quiet boot and minimal waits

With aggressive trimming and fixed network assumptions, a Pi 4 can approach this target for "camera+HTTP ready" state.

## Notes

- No Python is required by any custom runtime services in this project.
- Camera capture uses V4L2 device path (`/dev/video0`); ensure your kernel/libcamera stack exposes it on your chosen camera module.
- Host-local compile checks of `picam-pipeline` may fail on macOS because Linux V4L2 headers are missing; Buildroot cross-build is the source of truth.
- ONNX Runtime dependencies are pre-downloaded through Buildroot and staged into ONNX's local `mirror/` path to avoid HTTPS FetchContent failures.
- TensorFlow Lite also increases build time/footprint when enabled.

## ONNX Runtime (C/C++) usage

After build, ONNX Runtime headers/libs are available in the target sysroot.

- Header: `onnxruntime_c_api.h`
- Library: `libonnxruntime.so`

Cross-link pattern (example):

```sh
$TARGET_CC app.c -lonnxruntime -ldl -lpthread -lm -o app
```

## TensorFlow Lite (C/C++) usage

After build, TensorFlow Lite headers/libs are available in the target sysroot.

- C API header: `tensorflow/lite/c/c_api.h`
- Library: `libtensorflow-lite.so`

Cross-link pattern (example):

```sh
$TARGET_CXX app.cc -ltensorflow-lite -ldl -lpthread -lm -o app
```
