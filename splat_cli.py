#!/usr/bin/env python
# usage: ./splat_cli.py --open -o /tmp/google.pdf -b https://google.com
import argparse
import base64
import json
import pathlib

import requests

DEFAULT_LAMBDA_URL = "http://localhost:8080/2015-03-31/functions/function/invocations"

parser = argparse.ArgumentParser(
    description="Run against splat locally. Sample usage: ./splat_cli.py --open -o /tmp/google.pdf -b https://google.com"
)
parser.add_argument("--document-content", "-c", help="The content of the document")
parser.add_argument("--document-url", "-u", help="The URL of the document")
parser.add_argument("--browser-url", "-b", help="Use a playwright to browse to the url")
parser.add_argument("--renderer", "-r", help="The renderer to use", default="princexml")
parser.add_argument("--output-path", "-o", help="The path to save the output PDF", required=True)
parser.add_argument("--open", help="Open the resulting pdf", default=False, action="store_true")
parser.add_argument(
    "--lambda-url",
    help="Lambda URL to receive the payload body. Defaults to local dev setup.",
    default=DEFAULT_LAMBDA_URL,
)

args = parser.parse_args()

document_content = args.document_content
document_url = args.document_url
browser_url = args.browser_url
renderer = args.renderer
output_path = args.output_path
lambda_url = args.lambda_url


def call_lamdba(body: dict, raise_exception=True) -> tuple[int, dict, bytes]:
    response = requests.post(lambda_url, json={"body": json.dumps(body)}, timeout=60)
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


if __name__ == "__main__":
    body = {"renderer": renderer}
    if document_content:
        body["document_content"] = document_content
    elif document_url:
        body["document_url"] = document_url
    elif browser_url:
        body["browser_url"] = browser_url
    _, _, pdf_bytes = call_lamdba(body)
    pathlib.Path(output_path).write_bytes(pdf_bytes)
    if args.open:
        import os

        os.system(f"open {output_path}")  # noqa
