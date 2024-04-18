import base64
import json
from typing import Any
from uuid import uuid4

import boto3
import requests
from botocore.client import Config

LAMBDA_URL = "http://localhost:8080/2015-03-31/functions/function/invocations"


def gen_temp_key() -> str:
    return f"tmp/{str(uuid4())}.html"


def get_s3_client() -> Any:
    return boto3.client(
        "s3",
        aws_access_key_id="root",
        aws_secret_access_key="password",
        aws_session_token=None,
        endpoint_url="http://minio:9000",
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        verify=False,
    )


def call_lamdba(body: dict, raise_exception=True) -> tuple[int, dict, bytes]:
    response = requests.post(LAMBDA_URL, json={"body": json.dumps(body)}, timeout=60)
    if raise_exception:
        response.raise_for_status()
    data = response.json()
    status_code = data["statusCode"]
    is_base64_encoded = data["isBase64Encoded"]
    if is_base64_encoded:
        return status_code, {}, base64.b64decode(data["body"])
    else:
        body = json.loads(data["body"])
    if raise_exception and status_code != 200:
        raise Exception(body)

    return status_code, body, b""
