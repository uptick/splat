REPO ?= 305686791668.dkr.ecr.ap-southeast-2.amazonaws.com
TAG ?= latest
PROJECT ?= splat
IMAGE ?= ${REPO}/${PROJECT}:${TAG}
REGION ?= ap-southeast-2

# Print this help message
help:
	@echo
	@awk '/^#/ {c=substr($$0,3); next} c && /^([a-zA-Z].+):/{ print "  \033[32m" $$1 "\033[0m",c }{c=0}' $(MAKEFILE_LIST) |\
	sort |\
	column -s: -t |\
	less -R
	echo ${MAKEFILE_DIR}


# Build a container for the lambda
build:
	docker build -t ${IMAGE} .

# Build and push the docker container to ECR
publish:
	make login
	make build
	docker push ${IMAGE}

# Runs bash
shell:
	docker run --rm -it ${IMAGE} /bin/bash


# Runs a basic test
test: build
	docker run --rm -it ${IMAGE} /bin/bash -c "python3 splat/lambda_function.py"


login:
	docker login -u AWS -p $(shell aws ecr get-login-password --region ${REGION}) https://${REPO}
