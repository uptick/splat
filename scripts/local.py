import base64
import json
import pathlib

import requests

LAMBDA_URL = "http://localhost:8080/2015-03-31/functions/function/invocations"


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


_, _, pdf_bytes = call_lamdba({"renderer": "playwright", "document_content": "<h1>Hello world</h1>"})
pathlib.Path("/tmp/output.pdf").write_bytes(pdf_bytes)  # noqa
