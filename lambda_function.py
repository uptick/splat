import base64
import glob
import json
import logging
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse
from uuid import uuid4

import boto3
import pydantic
import requests
import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

logger = logging.getLogger("splat")

S3_RETRY_COUNT = 10

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN", ""),
    integrations=[
        AwsLambdaIntegration(),
    ],
)


class Payload(pydantic.BaseModel):
    # General Parameters
    javascript: bool = False
    check_license: bool = False

    # Input parameters
    document_content: str | None = None
    document_url: str | None = None

    # Output parameters
    bucket_name: str | None = None
    presigned_url: dict = pydantic.Field(default_factory=dict)


@dataclass
class Response:
    status_code: int = 200
    is_base64_encoded: bool = False
    body: str = ""
    headers: dict = field(default_factory=lambda: {"Content-Type": "application/json"})

    def as_dict(self) -> dict:
        return {
            "statusCode": self.status_code,
            "isBase64Encoded": self.is_base64_encoded,
            "body": self.body,
            "headers": self.headers,
        }


class SplatPDFGenerationFailure(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code

    def as_response(self) -> Response:
        return Response(
            status_code=self.status_code,
            body=json.dumps({"errors": [self.message]}),
        )


def init() -> None:
    # If there's any files in the font directory, export FONTCONFIG_PATH
    if any(f for f in os.listdir("fonts") if f != "fonts.conf"):
        os.environ["FONTCONFIG_PATH"] = "/var/task/fonts"
    cleanup()


def cleanup() -> None:
    print("splat|cleanup")
    extensions_to_remove = ["html", "pdf"]
    for extension in extensions_to_remove:
        for path in glob.glob(f"/tmp/*.{extension}"):  # noqa S108
            try:
                os.remove(path)
                print(f"splat|cleanup|removed|{path}")
            except FileNotFoundError:
                print(f"splat|cleanup|failed_to_remove|{path}")


def pdf_from_string(document_content: str, javascript: bool = False) -> str:
    print("splat|pdf_from_string")
    # Save document_content to file
    with open("/tmp/input.html", "w") as f:  # noqa S108
        f.write(document_content)
    return prince_handler("/tmp/input.html", javascript=javascript)  # noqa S108


def pdf_from_url(document_url: str, javascript: bool = False) -> str:
    print("splat|pdf_from_url")
    # Fetch document_url and save to file
    response = requests.get(document_url, timeout=120)
    if response.status_code != 200:
        raise SplatPDFGenerationFailure(
            f"Document was unable to be fetched from document_url provided. Server response: {response.content}",
            status_code=500,
        )
    with open("/tmp/input.html", "w") as f:  # noqa S108
        f.write(response.content.decode("utf-8"))
    return prince_handler("/tmp/input.html", javascript=javascript)  # noqa S108


def execute(cmd: list[str]) -> None:
    result = subprocess.run(cmd)  # noqa
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)


def prince_handler(input_filepath: str, output_filepath: str | None = None, javascript: bool = False) -> str:
    if not output_filepath:
        output_filepath = f"/tmp/{uuid4()}.pdf"  # noqa S108
    print("splat|prince_command_run")
    # Prepare command
    command = [
        "./prince",
        input_filepath,
        "-o",
        output_filepath,
        "--structured-log=normal",
        "--verbose",
    ]
    if javascript:
        command.append("--javascript")
    # Run command and capture output
    print(f"splat|invoke_prince {' '.join(command)}")
    execute(command)
    # Log prince output
    return output_filepath


# Entrypoint for AWS
def lambda_handler(event: dict, context: dict) -> dict:  # noqa
    try:
        resp = handler(event, context).as_dict()
    except SplatPDFGenerationFailure as e:
        resp = e.as_response().as_dict()
    except Exception as e:
        logger.error(f"splat|unknown_error|{str(e)}|stacktrace:", exc_info=True)
        resp = SplatPDFGenerationFailure(status_code=500, message=str(e)).as_response().as_dict()
    cleanup()
    return resp


def create_pdf(payload: Payload) -> str:
    """Creates the PDF and stores it from the payload"""
    if payload.document_content:
        output_filepath = pdf_from_string(payload.document_content, payload.javascript)
    elif payload.document_url:
        output_filepath = pdf_from_url(payload.document_url, payload.javascript)
    else:
        raise SplatPDFGenerationFailure(
            "Please specify either document_content or document_url",
            status_code=400,
        )
    return output_filepath


def deliver_pdf_to_s3_bucket(body: dict, output_filepath: str) -> Response:
    print("splat|bucket_save")
    # Upload to s3 and return URL
    bucket_name = body.get("bucket_name")
    key = "output.pdf"
    s3 = boto3.resource("s3")
    bucket = s3.Bucket(bucket_name)
    bucket.upload_file(output_filepath, key)  # noqa S108
    location = boto3.client("s3").get_bucket_location(Bucket=bucket_name)["LocationConstraint"]
    url = f"https://{bucket_name}.s3-{location}.amazonaws.com/{key}"
    return Response(
        body=json.dumps({"url": url}),
    )


def deliver_pdf_to_presigned_url(body: dict, output_filepath: str) -> Response:
    print("splat|presigned_url_save")
    presigned_url = body.get("presigned_url")
    try:
        urlparse(presigned_url["url"])
        assert presigned_url["fields"]
        assert presigned_url["url"]
    except Exception as e:  # noqa
        raise SplatPDFGenerationFailure(
            status_code=400,
            message="Invalid presigned URL",
        ) from e
    print("output_filepath=", output_filepath)
    with open(output_filepath, "rb") as f:
        # 5xx responses are normal for s3, recommendation is to try 10 times
        # https://aws.amazon.com/premiumsupport/knowledge-center/http-5xx-errors-s3/
        attempts = 0
        files = {"file": (output_filepath, f)}
        print(f'splat|posting_to_s3|{presigned_url["url"]}|{presigned_url["fields"].get("key")}')
        while attempts < S3_RETRY_COUNT:
            response = requests.post(presigned_url["url"], data=presigned_url["fields"], files=files, timeout=500)
            print(f"splat|s3_response|{response.status_code}")
            if response.status_code in [500, 503]:
                attempts += 1
                print("splat|s3_retry")
            else:
                break
        else:
            print("splat|s3_max_retry_reached")
            return Response(
                status_code=response.status_code,
                headers=response.headers,
                body=response.content,
            )
    if response.status_code != 204:
        print(f"splat|presigned_url_save|unknown_error|{response.status_code}|{response.content}")
        return Response(
            status_code=response.status_code,
            headers=response.headers,
            body=response.content,
        )
    else:
        return Response(
            status_code=201,
        )


def deliver_pdf_via_streaming_base64(output_filepath: str) -> Response:
    print("splat|stream_binary_response")
    # Otherwise just stream the pdf data back.
    with open(output_filepath, "rb") as f:
        binary_data = f.read()
    b64_encoded_pdf = base64.b64encode(binary_data).decode("utf-8")
    # Check size. lambda has a 6mb limit. Check if > 5.5mb
    if sys.getsizeof(b64_encoded_pdf) / 1024 / 1024 > 5.5:
        raise SplatPDFGenerationFailure(
            status_code=500,
            message="The resulting PDF is too large to stream back from lambda. Please use 'presigned_url' to upload it to s3 instead.",
        )
    return Response(
        headers={
            "Content-Type": "application/pdf",
        },
        body=b64_encoded_pdf,
        is_base64_encoded=True,
    )


def deliver_pdf(body: dict, output_filepath: str) -> Response:
    if body.get("bucket_name"):
        return deliver_pdf_to_s3_bucket(body, output_filepath)
    elif body.get("presigned_url"):
        return deliver_pdf_to_presigned_url(body, output_filepath)
    else:
        return deliver_pdf_via_streaming_base64(output_filepath)


def handler(event: dict, context: dict) -> Response:  # noqa
    """
    TODO:
    - [ ] use temporary files
    """
    print("splat|begin")

    # 1) Initialize
    init()

    # 2) Parse payload
    body = json.loads(event.get("body", "{}"))
    try:
        payload = Payload(**body)
    except pydantic.ValidationError as e:
        raise SplatPDFGenerationFailure(
            status_code=400,
            message="Invalid payload",
        ) from e

    # 3) Check licence if user is requesting that
    if payload.check_license:
        return check_license()

    print(f"splat|javascript={payload.javascript}")

    # 4) Read the html

    # 5) Generate PDF
    output_filepath = create_pdf(payload)

    # 6) Deliver PDF
    resp = deliver_pdf(body, output_filepath)
    return resp


def check_license() -> Response:
    """Checks the license file and returns the parsed license data."""
    tree = ET.parse("./prince-engine/license/license.dat")  # noqa
    parsed_license = {child.tag: (child.attrib, child.text) for child in tree.getroot() if child.tag != "signature"}
    is_demo_license = bool(list(filter(lambda x: x[0] == "option" and x[1].get("id") == "demo", parsed_license)))
    return Response(
        body=json.dumps({**parsed_license, "is_demo_license": is_demo_license}),
    )
