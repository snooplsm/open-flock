################################################################################
# picam-pipeline
################################################################################

PICAM_PIPELINE_VERSION = 1.0.0
PICAM_PIPELINE_SITE = $(BR2_EXTERNAL_PICAM_PATH)/package/picam-pipeline/src
PICAM_PIPELINE_SITE_METHOD = local


define PICAM_PIPELINE_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -O2 -Wall -Wextra \
		$(PICAM_PIPELINE_SITE)/picam_pipeline.c \
		-o $(@D)/picam-pipeline
endef

define PICAM_PIPELINE_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/picam-pipeline $(TARGET_DIR)/usr/bin/picam-pipeline
endef

$(eval $(generic-package))
