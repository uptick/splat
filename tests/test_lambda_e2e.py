import base64
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import pytest
import requests
from botocore.client import Config

LAMBDA_URL = "http://lambda:8080/2015-03-31/functions/function/invocations"
BUCKET_NAME = "test"


def gen_temp_key(format: str = "html") -> str:
    return f"tmp/{str(uuid4())}.{format}"


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
        body = json.loads(data.get("body")) if data.get("body") else {}
    if raise_exception and status_code not in {200, 201}:
        raise Exception(body)

    return status_code, body, b""


def test_check_license_returns_a_license_payload() -> None:
    status_code, body, _ = call_lamdba({"check_license": True})

    assert status_code == 200
    assert body["is_demo_license"] is False


def test_generating_pdf_with_fonts_disabled_returns_error():
    status_code, _, pdf_body = call_lamdba(
        {"document_content": Path("./tests/font-disabled.html").read_text(), "renderer": "princexml"},
        raise_exception=False,
    )
    assert status_code == 400


@pytest.mark.parametrize("renderer", ["princexml", "playwright"])
@pytest.mark.parametrize("browser_papersize", ["A4", "Letter"])
class TestRenderers:
    def test_generating_pdf_from_document_url(self, renderer: str, browser_papersize: str):
        s3_client = get_s3_client()

        key = gen_temp_key()
        s3_client.put_object(Bucket=BUCKET_NAME, Key=key, Body=b"<h1>Z</h1>")

        document_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": key},
        )

        status_code, _, pdf_body = call_lamdba(
            {"document_url": document_url, "renderer": renderer, "browser_papersize": browser_papersize},
        )

        assert b"Z" in pdf_body
        assert status_code == 200

    def test_generating_pdf_from_document_content(self, renderer: str, browser_papersize: str):
        """Send an embedded html document and receive the pdf bytes for it"""
        status_code, _, pdf_body = call_lamdba(
            {"document_content": "<h1>Z</h1>", "renderer": renderer, "browser_papersize": browser_papersize},
        )

        assert b"Z" in pdf_body
        assert status_code == 200

    def test_generating_pdf_from_browser_url(self, renderer: str, browser_papersize: str):
        status_code, _, pdf_body = call_lamdba(
            {"browser_url": "http://google.com", "renderer": renderer, "browser_papersize": browser_papersize},
        )

        assert b"Z" in pdf_body
        assert status_code == 200


class TestDeliveryMechanisms:
    def test_delivering_pdf_to_presigned_url(self):
        s3_client = get_s3_client()

        key = gen_temp_key(format="pdf")
        presigned_url = s3_client.generate_presigned_post(
            BUCKET_NAME,
            key,
        )

        status_code, _, _ = call_lamdba(
            {"document_content": "<h1>Z</h1>", "presigned_url": presigned_url},
        )

        obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
        pdf_bytes = obj["Body"].read()

        assert status_code == 201
        assert b"Z" in pdf_bytes

    def test_delivering_pdf_via_base64_encoding(self):
        status_code, _, pdf_bytes = call_lamdba(
            {"document_content": "<h1>Z</h1>"},
        )
        assert status_code == 200
        assert b"Z" in pdf_bytes

    def test_storing_pdf_via_bucket_name(self):
        status_code, body, _ = call_lamdba(
            {"document_content": "<h1>Z</h1>", "bucket_name": BUCKET_NAME},
        )
        assert status_code == 200
        assert body["presigned_url"]
        assert body["bucket"] == BUCKET_NAME
        assert body["key"].endswith(".pdf")


class TestInputValidation:
    def test_sending_invalid_presigned_url_an_error_is_returned(self):
        status_code, _, _ = call_lamdba(
            {"document_content": "<h1>Z</h1>", "presigned_url": "FAKE_URL"}, raise_exception=False
        )

        assert status_code == 400
