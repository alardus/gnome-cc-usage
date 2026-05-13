# Convenience targets for building cc-usage RPMs.
#
# Run from anywhere (paths are absolute). Outputs go under ./build/.
#
#   make sdist    # build source tarball from the working tree
#   make srpm     # build a source RPM (needed for COPR submissions)
#   make rpm      # build a binary RPM locally
#   make clean

NAME := cc-usage
SPEC := $(abspath $(lastword $(MAKEFILE_LIST)))
SPEC_DIR := $(dir $(SPEC))
ROOT := $(abspath $(SPEC_DIR)/../..)
VERSION := $(shell awk '/^Version:/ { print $$2 }' $(SPEC_DIR)/$(NAME).spec)
BUILD := $(SPEC_DIR)/build
TARBALL := $(BUILD)/$(NAME)-$(VERSION).tar.gz

.PHONY: all sdist srpm rpm clean

all: rpm

$(BUILD):
	mkdir -p $(BUILD)

# Source tarball produced via `git archive` so it includes only tracked files.
# The prefix matches what %autosetup -n cc-usage-VERSION expects.
sdist: $(TARBALL)
$(TARBALL): | $(BUILD)
	cd $(ROOT) && git archive --format=tar.gz \
		--prefix=$(NAME)-$(VERSION)/ \
		-o $(TARBALL) HEAD

srpm: $(TARBALL)
	rpmbuild -bs $(SPEC_DIR)/$(NAME).spec \
		--define "_topdir $(BUILD)" \
		--define "_sourcedir $(BUILD)"

rpm: $(TARBALL)
	rpmbuild -ba $(SPEC_DIR)/$(NAME).spec \
		--define "_topdir $(BUILD)" \
		--define "_sourcedir $(BUILD)"

clean:
	rm -rf $(BUILD)
