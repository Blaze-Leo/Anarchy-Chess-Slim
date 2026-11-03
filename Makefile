# Makefile - Anarchy Chess Docker build helpers.
# All work is delegated to script/build-docker.sh.
#
# Common targets:
#   make            -> package (clean, build, tag, verify, smoke)  [no push]
#   make deploy     -> package + push to Docker Hub
#   make push       -> push the already-built image
#   make help       -> list targets

SCRIPT := script/build-docker.sh

# Safe default: build and verify, but do not push.
.DEFAULT_GOAL := package

.PHONY: help package deploy all clean build tag verify smoke push

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

package: clean build tag verify smoke ## Build + verify the image (no push)
deploy: package push ## Build + verify + push to Docker Hub
all: deploy ## Alias for deploy

clean: ## Remove temp artifacts from code/
	@$(SCRIPT) clean

build: ## Docker build the local image
	@$(SCRIPT) build

tag: ## Re-tag the local image under the hub name
	@$(SCRIPT) tag

verify: ## Verify image contents match the repo
	@$(SCRIPT) verify

smoke: ## Run a container and probe the endpoints
	@$(SCRIPT) smoke

push: ## Push to Docker Hub
	@$(SCRIPT) push
