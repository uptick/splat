import json
import os
import re
from json import JSONDecodeError
from typing import Dict, List, Optional, cast
from uuid import uuid4

from botocore.config import Config

from .config import config


class SplatPDFGenerationFailure(Exception):
    pass


def strip_dangerous_s3_chars(filename: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_\.\-\s]", "", filename)


def pdf_with_splat(
    body_html: str,
    *,
    bucket_name: Optional[str] = None,
    s3_filepath: Optional[str] = None,
    fields: Optional[Dict] = None,
    conditions: Optional[List[List]] = None,
) -> Optional[bytes]:
    bucket_name = bucket_name or config.default_bucket_name
    if not bucket_name:
        raise SplatPDFGenerationFailure(
            "Invalid configuration: no bucket name provided"
        )

    is_streaming = not bool(s3_filepath)

    session = config.get_session_fn()
    lambda_client = session.client(
        "lambda", region_name=config.function_region, config=Config(read_timeout=120)
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
    html_key = os.path.join(bucket_name, "tmp", f"{uuid4()}.html")

    s3_client.put_object(
        Body=body_html,
        Bucket=bucket_name,
        Key=html_key,
        Tagging=config.default_tagging,
    )

    document_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": html_key},
        ExpiresIn=1800,
    )

    splat_body = json.dumps(
        {"document_url": document_url, "presigned_url": presigned_url}
    )

    response = lambda_client.invoke(
        FunctionName=config.function_name,
        Payload=json.dumps({"body": splat_body}),
    )

    # Remove the temporary html file from s3
    config.delete_key_fn(bucket_name, html_key)

    # Check response of the invocation. Note that a successful invocation doesn't mean the PDF was generated.
    if response.get("StatusCode") != 200:
        raise SplatPDFGenerationFailure(
            "Invalid response while invoking splat lambda -"
            f" {response.get('StatusCode')}"
        )

    # Parse lambda response
    try:
        splat_response = json.loads(response["Payload"].read().decode("utf-8"))
    except (KeyError, AttributeError):
        raise SplatPDFGenerationFailure("Invalid lambda response format")
    except JSONDecodeError:
        raise SplatPDFGenerationFailure("Error decoding splat response body as json")

    # ==== Success ====
    if splat_response.get("statusCode") == 201:
        # If no s3 path, read the pdf from the temp location we had splat save it to, delete it, and return the pdf file as bytes.
        if is_streaming:
            obj = s3_client.get_object(Bucket=bucket_name, Key=destination_path)
            pdf_bytes = obj["Body"].read()
            try:
                config.delete_key_fn(bucket_name, destination_path)
            except Exception as e:
                pass
            return cast(bytes, pdf_bytes)
        return None

    # ==== Failure ====
    # Lambda timeout et al.
    elif error_message := splat_response.get("errorMessage"):
        raise SplatPDFGenerationFailure(
            f"Error returned from lambda invocation: {error_message}"
        )
    # All other errors
    else:
        # Try to extract an error message from splat response
        try:
            splat_error = json.loads(splat_response["body"])["errors"][0]
        except (KeyError, JSONDecodeError):
            splat_error = splat_response
        raise SplatPDFGenerationFailure(f"Error returned from splat: {splat_error}")
