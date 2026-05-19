# Convenience target for building a cc-usage .deb via fpm.
#
# Requires: fpm (gem install fpm --no-document), pip3
#
#   make -C packaging/deb        # build the .deb
#   make -C packaging/deb clean

NAME     := cc-usage
VERSION  := 0.1.1
ARCH     := all
SPEC_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROOT     := $(abspath $(SPEC_DIR)/../..)
BUILD    := $(SPEC_DIR)/build
STAGING  := $(BUILD)/staging
DEB      := $(BUILD)/$(NAME)_$(VERSION)-1_$(ARCH).deb
FPM      := $(HOME)/bin/fpm

.PHONY: all deb clean

all: deb

deb: | $(BUILD)
	rm -rf $(STAGING)
	mkdir -p $(STAGING)

	# Build wheel from current source and install into staging tree.
	pip wheel $(ROOT) --no-deps -w $(BUILD)/wheeldir -q
	pip install --no-index --find-links $(BUILD)/wheeldir \
		--prefix=/usr --root=$(STAGING) --no-deps --ignore-installed cc-usage

	# Desktop entry and symbolic icons.
	install -Dm0644 $(ROOT)/src/cc_usage/_resources/desktop/cc-usage.desktop \
		$(STAGING)/usr/share/applications/cc-usage.desktop
	for icon in cc-usage-symbolic cc-usage-warn-symbolic cc-usage-crit-symbolic; do \
		install -Dm0644 $(ROOT)/src/cc_usage/_resources/icons/$${icon}.svg \
			$(STAGING)/usr/share/icons/hicolor/scalable/status/$${icon}.svg; \
	done

	# License and docs.
	install -Dm0644 $(ROOT)/LICENSE \
		$(STAGING)/usr/share/doc/$(NAME)/copyright
	install -Dm0644 $(ROOT)/README.md \
		$(STAGING)/usr/share/doc/$(NAME)/README.md

	$(FPM) -s dir -t deb \
		--name $(NAME) \
		--version $(VERSION) \
		--iteration 1 \
		--architecture $(ARCH) \
		--license MIT \
		--description "Tray indicator for Claude Code usage" \
		--url "https://github.com/alardus/gnome-cc-usage" \
		--maintainer "Alexander Bykov <alardus@gmail.com>" \
		--depends "python3" \
		--depends "python3-gi" \
		--depends "gir1.2-ayatanaappindicator3-0.1" \
		--depends "gir1.2-notify-0.7" \
		--depends "python3-requests" \
		--deb-recommends "gnome-shell-extension-appindicator" \
		--after-install $(SPEC_DIR)/postinst \
		--after-remove $(SPEC_DIR)/postrm \
		--package $(DEB) \
		-C $(STAGING) \
		usr

$(BUILD):
	mkdir -p $(BUILD)

clean:
	rm -rf $(BUILD)
