#	docker build --platform linux/amd64 -t ${IMAGE} --target=base .
FROM public.ecr.aws/lambda/python:3.9-x86_64
ENV PRINCE_FILENAME=prince-14.1-linux-generic-x86_64
RUN yum clean all \
    && yum install -y unzip giflib \
    && curl -O -J https://www.princexml.com/download/prince-14.2-aws-lambda.zip  \
    && unzip prince-14.2-aws-lambda.zip \
    && rm -rf /var/cache/yum \
    && rm prince-14.2-aws-lambda.zip
COPY requirements.txt ./
RUN pip3 install -r requirements.txt
ADD splat splat/
ENTRYPOINT [""]
CMD ["/bin/bash"]
CMD ["run_sql.main"]