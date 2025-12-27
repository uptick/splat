# Define function directory
ARG FUNCTION_DIR="/var/task"

FROM mcr.microsoft.com/playwright/python:v1.57.0-jammy AS build-image

# Install aws-lambda-cpp build dependencies
RUN apt-get update && \
    apt-get install -y \
    g++ \
    make \
    cmake \
    libcurl4-openssl-dev && \
    rm -rf /var/lib/apt/lists/*


# Include global arg in this stage of the build
ARG FUNCTION_DIR
# Create function directory
RUN mkdir -p ${FUNCTION_DIR}
WORKDIR ${FUNCTION_DIR}

# Install the runtime interface client
COPY lambda_requirements.txt fonts.zip* ./
RUN pip3 install -r lambda_requirements.txt --target ${FUNCTION_DIR}

# ------------------------------------------------------

# Multi-stage build: grab a fresh copy of the base image
FROM mcr.microsoft.com/playwright/python:v1.57.0-jammy

# Include global arg in this stage of the build
ARG FUNCTION_DIR
# Set working directory to function root directory
WORKDIR ${FUNCTION_DIR}

# Copy in the build image dependencies
COPY --from=build-image ${FUNCTION_DIR} ${FUNCTION_DIR}

COPY ./entry_script.sh /entry_script.sh
RUN curl -Lo aws-lambda-rie \
    https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/latest/download/aws-lambda-rie && \
    chmod +x aws-lambda-rie && \
    mv aws-lambda-rie /usr/local/bin/aws-lambda-rie

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libavif13 \
    unzip \
    libgif7 && \
    rm -rf /var/lib/apt/lists/*

# Download and extract PrinceXML
RUN curl -O -J https://www.princexml.com/download/prince-14.2-aws-lambda.zip && \
    unzip prince-14.2-aws-lambda.zip && \
    rm prince-14.2-aws-lambda.zip


RUN rm -rf /var/task/fonts || true
RUN mkdir -p /var/task/fonts || true
COPY splat-private/font[s] /var/task/fonts

COPY splat-private/license.dat ./prince-engine/license/license.dat
COPY lambda_function.py ./

ENTRYPOINT [ "/entry_script.sh","lambda_function.lambda_handler" ]
