#!/usr/bin/env -S uv run -s
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "boto3",
#     "requests",
#     "typer",
# ]
# ///


import argparse
import base64
import enum
import json
import subprocess

import boto3
import requests
import typer

DEFAULT_LAMBDA_URL = "http://localhost:8080/2015-03-31/functions/function/invocations"

parser = argparse.ArgumentParser(
    description="Run against splat locally. Sample usage: ./splat_cli.py --open -o /tmp/google.pdf -b https://google.com"
)


class Renderer(enum.StrEnum):
    princexml = "princexml"
    browser = "browser"


def invoke_function(
    document_content: str | None = typer.Option(None, "--content", "-c"),
    document_url: str | None = typer.Option(None, "--url", "-u"),
    browser_url: str | None = typer.Option(None, "--browser-url", "-b"),
    renderer: Renderer = typer.Option(Renderer.princexml, "--renderer", "-r"),
    output_path: str = typer.Option("/tmp/output.pdf", "--output", "-o"),  # noqa
    lambda_url: str = typer.Option(DEFAULT_LAMBDA_URL, "--lambda-url", "-l"),
    function_name: str | None = typer.Option(None, "--function-name", "-f"),
) -> bytes:
    """

    Usage:
    Invoke using a local function url
    ./splat_cli.py -o /tmp/google.pdf -b https://google.com

    Invoke using a deployed lambda against an embedded document
    ./splat_cli.py -o /tmp/google.pdf -c "<h1> hi </h1>" --function-name splat-staging
    """
    if not (document_content or document_url or browser_url):
        print("Please provide document content or document url or browser url")
        raise typer.Exit(code=1)

    body = {"renderer": renderer}
    if document_content:
        body["document_content"] = document_content
    elif document_url:
        body["document_url"] = document_url
    elif browser_url:
        body["browser_url"] = browser_url

    if function_name:
        lambda_client = boto3.client("lambda")
        response = lambda_client.invoke(FunctionName=function_name, Payload=json.dumps({"body": json.dumps(body)}))
        status_code = response.get("StatusCode")
        if status_code not in {200, 201}:
            print("Something went wrong!")
            raise Exception(response)
        data = json.loads(response["Payload"].read().decode("utf-8"))
        status_code = data["statusCode"]
        is_base64_encoded = data["isBase64Encoded"]
    else:
        response = requests.post(lambda_url, json={"body": json.dumps(body)}, timeout=60)
        response.raise_for_status()
        data = response.json()
        status_code = data["statusCode"]
        is_base64_encoded = data["isBase64Encoded"]

    if is_base64_encoded:
        body = base64.b64decode(data["body"])
    else:
        body = json.loads(data.get("body")) if data.get("body") else {}

    if output_path:
        print(f"Writing to: {output_path}")
        with open(output_path, "wb") as f:
            f.write(body)  # noqa

        subprocess.run(["open", output_path])  # noqa


if __name__ == "__main__":
    typer.run(invoke_function)
