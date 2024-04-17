import base64
import json
import re
from json import JSONDecodeError
from typing import cast
from uuid import uuid4

from botocore.config import Config

from .config import config


class SplatPDFGenerationFailure(Exception):
    pass


def strip_dangerous_s3_chars(filename: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_\.\-\s]", "", filename)


def pdf_from_html(
    body_html: str,
    *,
    bucket_name: str | None = None,
    s3_filepath: str | None = None,
    javascript: bool = False,
    fields: dict | None = None,
    conditions: list[list] | None = None,
) -> bytes | None:
    """Generates a pdf from html using the splat lambda function.

    :param body_html: the html to convert to pdf
    :param bucket_name: the bucket to upload the html to. defaults to config.default_bucket_name
    :param s3_filepath: the path to upload the pdf to. defaults to a random path in the bucket
    :param fields: additional fields to add to the presigned url
    :param conditions: additional conditions to add to the presigned url
    """
    bucket_name = bucket_name or config.default_bucket_name
    if not bucket_name:
        raise SplatPDFGenerationFailure("Invalid configuration: no bucket name provided")

    is_streaming = not bool(s3_filepath)

    session = config.get_session_fn()
    lambda_client = session.client(
        "lambda",
        region_name=config.function_region,
        config=Config(read_timeout=60 * 15, retries={"max_attempts": 0}),
    )
    s3_client = session.client("s3")

    destination_path = s3_filepath or f"tmp/{uuid4()}.pdf"
    fields = fields or {}
    conditions = conditions or []

    presigned_url = s3_client.generate_presigned_post(
        bucket_name,
        destination_path,
        ExpiresIn=5 * 60,  # seconds
        Fields={
            "Content-Type": "application/pdf",
            **fields,
        },
        Conditions=[["starts-with", "$Content-Type", "application/pdf"], *conditions],
    )

    # Upload body HTML to s3 and get a link to hand to splat
    tmp_html_key = config.get_tmp_html_key_fn()

    s3_client.put_object(
        Body=body_html,
        Bucket=bucket_name,
        Key=tmp_html_key,
        Tagging=config.default_tagging,
    )

    document_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": tmp_html_key},
        ExpiresIn=1800,
    )

    splat_body = json.dumps(
        {
            "document_url": document_url,
            "presigned_url": presigned_url,
            "javascript": javascript,
        }
    )

    response = lambda_client.invoke(
        FunctionName=config.function_name,
        Payload=json.dumps({"body": splat_body}),
    )

    # Remove the temporary html file from s3
    config.delete_key_fn(bucket_name, tmp_html_key)

    # Check response of the invocation. Note that a successful invocation doesn't mean the PDF was generated.
    if response.get("StatusCode") != 200:
        raise SplatPDFGenerationFailure(
            "Invalid response while invoking splat lambda -" f" {response.get('StatusCode')}"
        )

    # Parse lambda response
    try:
        splat_response = json.loads(response["Payload"].read().decode("utf-8"))
    except (KeyError, AttributeError) as exc:
        raise SplatPDFGenerationFailure("Invalid lambda response format") from exc
    except JSONDecodeError as exc:
        raise SplatPDFGenerationFailure("Error decoding splat response body as json") from exc

    # ==== Success ====
    if splat_response.get("statusCode") == 201:
        # If no s3 path, read the pdf from the temp location we had splat save it to, delete it, and return the pdf file as bytes.
        if is_streaming:
            obj = s3_client.get_object(Bucket=bucket_name, Key=destination_path)
            pdf_bytes = obj["Body"].read()
            try:
                config.delete_key_fn(bucket_name, destination_path)
            except Exception: # noqa
                pass
            return cast(bytes, pdf_bytes)
        return None

    # ==== Failure ====
    # Lambda timeout et al.
    elif error_message := splat_response.get("errorMessage"):
        raise SplatPDFGenerationFailure(f"Error returned from lambda invocation: {error_message}")
    # All other errors
    else:
        # Try to extract an error message from splat response
        try:
            splat_error = json.loads(splat_response["body"])["errors"][0]
        except (KeyError, JSONDecodeError):
            splat_error = splat_response
        raise SplatPDFGenerationFailure(f"Error returned from splat: {splat_error}")


def pdf_from_html_without_s3(
    body_html: str,
    javascript: bool = False,
) -> bytes:
    """Generates a pdf from html without using s3. This is useful for small pdfs and html documents.

    The maximum size of the html document is 6MB. The maximum size of the pdf is 6MB.
    """
    session = config.get_session_fn()
    lambda_client = session.client(
        "lambda",
        region_name=config.function_region,
        config=Config(read_timeout=60 * 15, retries={"max_attempts": 0}),
    )

    splat_body = json.dumps({"document_content": body_html, "javascript": javascript})

    response = lambda_client.invoke(
        FunctionName=config.function_name,
        Payload=json.dumps({"body": splat_body}),
    )

    # Check response of the invocation. Note that a successful invocation doesn't mean the PDF was generated.
    if response.get("StatusCode") != 200:
        raise SplatPDFGenerationFailure(
            "Invalid response while invoking splat lambda -" f" {response.get('StatusCode')}"
        )

    # Parse lambda response
    try:
        splat_response = json.loads(response["Payload"].read().decode("utf-8"))
    except (KeyError, AttributeError) as exc:
        raise SplatPDFGenerationFailure("Invalid lambda response format") from exc
    except JSONDecodeError as exc:
        raise SplatPDFGenerationFailure("Error decoding splat response body as json") from exc

    # ==== Success ====
    if splat_response.get("statusCode") == 200:
        return base64.b64decode(splat_response.get("body"))
    # ==== Failure ====
    # Lambda timeout et al.
    elif error_message := splat_response.get("errorMessage"):
        raise SplatPDFGenerationFailure(f"Error returned from lambda invocation: {error_message}")
    # All other errors
    else:
        # Try to extract an error message from splat response
        try:
            splat_error = json.loads(splat_response["body"])["errors"][0]
        except (KeyError, JSONDecodeError):
            splat_error = splat_response
        raise SplatPDFGenerationFailure(f"Error returned from splat: {splat_error}")
