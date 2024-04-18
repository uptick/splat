#	docker build --platform linux/amd64 -t ${IMAGE} --target=base .
# Target: base
FROM public.ecr.aws/lambda/python:3.11-x86_64 as base
ENV PRINCE_FILENAME=prince-14.1-linux-generic-x86_64
RUN yum clean all \
    && yum install -y unzip giflib \
    && curl -O -J https://www.princexml.com/download/prince-14.2-aws-lambda.zip  \
    && unzip prince-14.2-aws-lambda.zip \
    && rm -rf /var/cache/yum \
    && rm prince-14.2-aws-lambda.zip
# Copy requirements, and optionally the fonts.zip if it exists.
COPY lambda_requirements.txt fonts.zip* ./
RUN pip3 install -r lambda_requirements.txt
# Fonts zip may not exist, so || true it.
CMD rm -rf /var/task/fonts || true
COPY font[s] /var/task/fonts
COPY license.dat ./prince-engine/license/license.dat
COPY lambda_function.py ./
CMD ["lambda_function.lambda_handler"]
