import base64
import enum
import json
import logging
import os
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse

import boto3
import pydantic
import requests
import sentry_sdk
from playwright.sync_api import sync_playwright
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration

logger = logging.getLogger("splat")

S3_RETRY_COUNT = 10

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN", ""),
    integrations=[
        AwsLambdaIntegration(),
    ],
)


class Renderers(str, enum.Enum):
    playwright = "playwright"
    princexml = "princexml"


class Payload(pydantic.BaseModel):
    # NOTE: When updating this model, also update the equivalent documentation
    # General Parameters
    javascript: bool = False
    check_license: bool = False

    # Input parameters
    ## Embed the document content as a string
    document_content: str | None = None
    ## Fetch the document from a URL, store it and render it
    document_url: str | None = None
    ## Browse the document in a browser before rendering
    browser_url: str | None = None
    browser_headers: dict = pydantic.Field(default_factory=dict)
    renderer: Renderers = Renderers.princexml

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


def playwright_page_to_pdf(browser_url: str, headers: dict, output_filepath: str) -> None:
    print("splat|playwright_handler|url=", browser_url)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        context.set_extra_http_headers(headers)
        page = context.new_page()
        page.goto(
            browser_url,
            wait_until="domcontentloaded",
        )
        page.emulate_media(media="print")
        page.pdf(path=output_filepath, format="A4")


def playwright_page_to_html_string(browser_url: str, headers: dict) -> str:
    print("splat|playwright_handler|url=", browser_url)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        context.set_extra_http_headers(headers)
        page = context.new_page()
        page.goto(
            browser_url,
            wait_until="domcontentloaded",
        )
        page.emulate_media(media="print")
        return page.content()


def pdf_from_document_content(payload: Payload, output_filepath: str) -> None:
    """Generates pdf from string content of the document"""
    print("splat|pdf_from_document_content")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html") as temporary_html_file:
        assert payload.document_content
        temporary_html_file.write(payload.document_content)
        temporary_html_file.flush()
        if payload.renderer == Renderers.princexml:
            prince_handler(temporary_html_file.name, output_filepath, payload.javascript)
        else:
            playwright_page_to_pdf(f"file://{temporary_html_file.name}", payload.browser_headers, output_filepath)


def pdf_from_document_url(payload: Payload, output_filepath: str) -> None:
    """Generates pdf from a remote html document"""
    print("splat|pdf_from_document_url")
    response = requests.get(payload.document_url, timeout=120)
    if response.status_code != 200:
        raise SplatPDFGenerationFailure(
            f"Document was unable to be fetched from document_url provided. Server response: {response.content}",
            status_code=500,
        )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html") as temporary_html_file:
        temporary_html_file.write(response.content.decode("utf-8"))
        temporary_html_file.flush()
        if payload.renderer == Renderers.princexml:
            prince_handler(temporary_html_file.name, output_filepath, payload.javascript)
        else:
            playwright_page_to_pdf(f"file://{temporary_html_file.name}", payload.browser_headers, output_filepath)


def pdf_from_browser_url(payload: Payload, output_filepath: str) -> None:
    """Generates pdf by visiting a browser url"""
    print("splat|pdf_from_browser_url")
    # First we need to visit the browser with playwright and save the html
    assert payload.browser_url
    if payload.renderer == Renderers.princexml:
        html = playwright_page_to_html_string(payload.browser_url, payload.browser_headers)
        pdf_from_document_content(Payload(document_content=html, renderer=Renderers.princexml), output_filepath)
    else:
        playwright_page_to_pdf(payload.browser_url, payload.browser_headers, output_filepath)


def execute(cmd: list[str]) -> None:
    result = subprocess.run(cmd)  # noqa
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)


def prince_handler(input_filepath: str, output_filepath: str, javascript: bool = False) -> None:
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


def create_pdf(payload: Payload, output_filepath: str) -> str:
    """Creates the PDF and stores it from the payload"""
    if payload.document_content:
        pdf_from_document_content(payload, output_filepath)
    elif payload.document_url:
        pdf_from_document_url(payload, output_filepath)
    elif payload.browser_url:
        pdf_from_browser_url(payload, output_filepath)
    else:
        raise SplatPDFGenerationFailure(
            "Please specify either document_content or document_url or browser_url in the payload.",
            status_code=400,
        )
    return output_filepath


def deliver_pdf_to_s3_bucket(payload: Payload, output_filepath: str) -> Response:
    print("splat|bucket_save")
    key = f"{uuid.uuid4()}.pdf"
    s3 = boto3.resource("s3")
    bucket = s3.Bucket(payload.bucket_name)
    bucket.upload_file(output_filepath, key)

    presigned_url = boto3.client("s3").generate_presigned_url(
        "get_object",
        Params={"Bucket": payload.bucket_name, "Key": key},
    )
    return Response(
        body=json.dumps(
            {
                "bucket": payload.bucket_name,
                "key": key,
                "presigned_url": presigned_url,
            }
        ),
    )


def deliver_pdf_to_presigned_url(payload: Payload, output_filepath: str) -> Response:
    print("splat|presigned_url_save")
    presigned_url = payload.presigned_url
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


def deliver_pdf(payload: Payload, output_filepath: str) -> Response:
    if payload.bucket_name:
        return deliver_pdf_to_s3_bucket(payload, output_filepath)
    elif payload.presigned_url:
        return deliver_pdf_to_presigned_url(payload, output_filepath)
    else:
        return deliver_pdf_via_streaming_base64(output_filepath)


# Entrypoint for AWS
def lambda_handler(event: dict, context: dict) -> dict:  # noqa
    try:
        resp = handle_event(event).as_dict()
    except SplatPDFGenerationFailure as e:
        resp = e.as_response().as_dict()
    except Exception as e:
        logger.error(f"splat|unknown_error|{str(e)}|stacktrace:", exc_info=True)
        resp = SplatPDFGenerationFailure(status_code=500, message=str(e)).as_response().as_dict()
    return resp


def handle_event(event: dict) -> Response:  # noqa
    """The main body of the lambda sans error handling"""
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
            message=f"Invalid payload: {e}",
        ) from e

    # 3) Check licence if user is requesting that
    if payload.check_license:
        return check_license()

    print(f"splat|javascript={payload.javascript}")
    print(f"splat|renderer={payload.renderer}")

    # 4) Generate PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf") as output_pdf:
        output_filepath = output_pdf.name
        create_pdf(payload, output_filepath)

        # 5) Deliver  the PDF
        resp = deliver_pdf(payload, output_filepath)
    return resp


def check_license() -> Response:
    """Checks the license file and returns the parsed license data."""
    tree = ET.parse("./prince-engine/license/license.dat")  # noqa
    parsed_license = {child.tag: (child.attrib, child.text) for child in tree.getroot() if child.tag != "signature"}
    is_demo_license = bool(list(filter(lambda x: x[0] == "option" and x[1].get("id") == "demo", parsed_license)))
    return Response(
        body=json.dumps({**parsed_license, "is_demo_license": is_demo_license}),
    )
