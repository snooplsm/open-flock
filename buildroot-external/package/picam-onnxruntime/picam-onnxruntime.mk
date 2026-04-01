################################################################################
# picam-onnxruntime
################################################################################

PICAM_ONNXRUNTIME_VERSION = 1.18.1
PICAM_ONNXRUNTIME_SITE = https://github.com/microsoft/onnxruntime/archive/refs/tags
PICAM_ONNXRUNTIME_SOURCE = v$(PICAM_ONNXRUNTIME_VERSION).tar.gz
PICAM_ONNXRUNTIME_SUBDIR = cmake
PICAM_ONNXRUNTIME_LICENSE = MIT
PICAM_ONNXRUNTIME_LICENSE_FILES = LICENSE
PICAM_ONNXRUNTIME_INSTALL_STAGING = YES
PICAM_ONNXRUNTIME_SUPPORTS_IN_SOURCE_BUILD = NO
PICAM_ONNXRUNTIME_DEPENDENCIES = host-python3 host-protobuf eigen

# ONNX Runtime uses FetchContent for dependencies. Buildroot's host-cmake
# has HTTPS downloads disabled, so pre-download required archives with Buildroot
# and stage them into <onnxruntime-source>/mirror/<url-without-https://>.
PICAM_ONNXRUNTIME_MIRROR_DEPS = \
	https://github.com/abseil/abseil-cpp/archive/refs/tags/20240116.0.zip \
	https://github.com/HowardHinnant/date/archive/refs/tags/v3.0.1.zip \
	https://github.com/google/nsync/archive/refs/tags/1.26.0.zip \
	https://github.com/google/flatbuffers/archive/refs/tags/v23.5.26.zip \
	https://github.com/protocolbuffers/utf8_range/archive/72c943dea2b9240cd09efde15191e144bc7c7d38.zip \
	https://github.com/protocolbuffers/protobuf/archive/refs/tags/v21.12.zip \
	https://github.com/nlohmann/json/archive/refs/tags/v3.10.5.zip \
	https://github.com/boostorg/mp11/archive/refs/tags/boost-1.82.0.zip \
	https://github.com/google/re2/archive/refs/tags/2022-06-01.zip \
	https://github.com/microsoft/GSL/archive/refs/tags/v4.0.0.zip \
	https://github.com/dcleblanc/SafeInt/archive/refs/tags/3.0.28.zip \
	https://github.com/onnx/onnx/archive/refs/tags/v1.16.0.zip

PICAM_ONNXRUNTIME_EXTRA_DOWNLOADS = $(PICAM_ONNXRUNTIME_MIRROR_DEPS)

define PICAM_ONNXRUNTIME_STAGE_MIRROR_DEPS
	set -e; \
	for u in $(PICAM_ONNXRUNTIME_MIRROR_DEPS); do \
		rel=$${u#https://}; \
		dst="$(@D)/mirror/$$rel"; \
		src="$(DL_DIR)/$${u##*/}"; \
		mkdir -p "$$(dirname "$$dst")"; \
		cp -f "$$src" "$$dst"; \
	done
endef

PICAM_ONNXRUNTIME_POST_EXTRACT_HOOKS += PICAM_ONNXRUNTIME_STAGE_MIRROR_DEPS

PICAM_ONNXRUNTIME_CONF_OPTS += \
	-Donnxruntime_BUILD_SHARED_LIB=ON \
	-Donnxruntime_BUILD_UNIT_TESTS=OFF \
	-Donnxruntime_BUILD_BENCHMARKS=OFF \
	-Donnxruntime_BUILD_CSHARP=OFF \
	-Donnxruntime_BUILD_JAVA=OFF \
	-Donnxruntime_BUILD_NODEJS=OFF \
	-Donnxruntime_BUILD_OBJC=OFF \
	-Donnxruntime_BUILD_APPLE_FRAMEWORK=OFF \
	-Donnxruntime_USE_CUDA=OFF \
	-Donnxruntime_USE_ROCM=OFF \
	-Donnxruntime_USE_OPENVINO=OFF \
	-Donnxruntime_USE_TENSORRT=OFF \
	-Donnxruntime_USE_MIGRAPHX=OFF \
	-Donnxruntime_USE_DNNL=OFF \
	-Donnxruntime_USE_XNNPACK=OFF \
	-Donnxruntime_ENABLE_PYTHON=OFF \
	-Donnxruntime_ENABLE_LTO=ON \
	-Donnxruntime_MINIMAL_BUILD=ON \
	-Donnxruntime_USE_PREINSTALLED_EIGEN=ON \
	-Deigen_SOURCE_PATH=$(STAGING_DIR)/usr/include/eigen3 \
	-DONNX_CUSTOM_PROTOC_EXECUTABLE=$(HOST_DIR)/bin/protoc

$(eval $(cmake-package))
