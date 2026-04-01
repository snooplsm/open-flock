################################################################################
# picam-httpd
################################################################################

PICAM_HTTPD_VERSION = 1.0.0
PICAM_HTTPD_SITE = $(BR2_EXTERNAL_PICAM_PATH)/package/picam-httpd/src
PICAM_HTTPD_SITE_METHOD = local


define PICAM_HTTPD_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -O2 -Wall -Wextra \
		$(PICAM_HTTPD_SITE)/picam_httpd.c \
		-o $(@D)/picam-httpd
endef

define PICAM_HTTPD_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/picam-httpd $(TARGET_DIR)/usr/bin/picam-httpd
endef

$(eval $(generic-package))
