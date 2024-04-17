import base64
import glob
import json
import logging
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from uuid import uuid4

import boto3
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


def init():
    # If there's any files in the font directory, export FONTCONFIG_PATH
    if any(f for f in os.listdir("fonts") if f != "fonts.conf"):
        os.environ["FONTCONFIG_PATH"] = "/var/task/fonts"
    cleanup()


def cleanup():
    print("splat|cleanup")
    extensions_to_remove = ["html", "pdf"]
    for extension in extensions_to_remove:
        for path in glob.glob(f"/tmp/*.{extension}"):
            try:
                os.remove(path)
                print(f"splat|cleanup|removed|{path}")
            except FileNotFoundError:
                print(f"splat|cleanup|failed_to_remove|{path}")


def pdf_from_string(document_content, javascript=False):
    print("splat|pdf_from_string")
    # Save document_content to file
    with open("/tmp/input.html", "w") as f:
        f.write(document_content)
    return prince_handler("/tmp/input.html", javascript=javascript)


def pdf_from_url(document_url, javascript=False):
    print("splat|pdf_from_url")
    # Fetch document_url and save to file
    response = requests.get(document_url, timeout=120)
    if response.status_code != 200:
        return respond(
            {
                "statusCode": 500,
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": json.dumps(
                    {
                        "errors": [
                            "Document was unable to be fetched from document_url provided. Server response: {response.content}"
                        ]
                    }
                ),
                "isBase64Encoded": False,
            }
        )
    with open("/tmp/input.html", "w") as f:
        f.write(response.content.decode("utf-8"))
    return prince_handler("/tmp/input.html", javascript=javascript)


def execute(cmd: str) -> None:
    result = subprocess.run(cmd)  # noqa
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)


def prince_handler(input_filepath, output_filepath=None, javascript=False):
    if not output_filepath:
        output_filepath = f"/tmp/{uuid4()}.pdf"
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


def respond(payload):
    cleanup()
    return payload


# Entrypoint for AWS
def lambda_handler(event, context):
    try:
        print("splat|begin")
        init()
        # Parse payload - assumes json
        body = json.loads(event.get("body"))
        # Check licence if user is requesting that
        if body.get("check_license", False):
            return check_license()
        javascript = bool(body.get("javascript", False))
        print(f"splat|javascript={javascript}")
        # Create PDF
        try:
            if body.get("document_content"):
                output_filepath = pdf_from_string(body.get("document_content"), javascript)
            elif body.get("document_url"):
                output_filepath = pdf_from_url(body.get("document_url"), javascript)
            else:
                return respond(
                    {
                        "statusCode": 400,
                        "headers": {
                            "Content-Type": "application/json",
                        },
                        "body": json.dumps({"errors": ["Please specify either document_content or document_url"]}),
                        "isBase64Encoded": False,
                    }
                )
        except subprocess.CalledProcessError as e:
            print(f"splat|calledProcessError|{str(e)}")
            return respond(
                {
                    "statusCode": 500,
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "body": json.dumps({"errors": [str(e)]}),
                    "isBase64Encoded": False,
                }
            )

        # Return PDF
        if body.get("bucket_name"):
            print("splat|bucket_save")
            # Upload to s3 and return URL
            bucket_name = body.get("bucket_name")
            key = "output.pdf"
            s3 = boto3.resource("s3")
            bucket = s3.Bucket(bucket_name)
            bucket.upload_file("/tmp/output.pdf", key)
            location = boto3.client("s3").get_bucket_location(Bucket=bucket_name)["LocationConstraint"]
            url = f"https://{bucket_name}.s3-{location}.amazonaws.com/{key}"

            return respond(
                {
                    "statusCode": 200,
                    "headers": {
                        "Content-Type": "application/json",
                    },
                    "body": json.dumps({"url": url}),
                    "isBase64Encoded": False,
                }
            )
        elif body.get("presigned_url"):
            print("splat|presigned_url_save")
            presigned_url = body.get("presigned_url")
            if not urlparse(presigned_url["url"]).netloc.endswith("amazonaws.com"):
                return respond(
                    {
                        "statusCode": 400,
                        "headers": {
                            "Content-Type": "application/json",
                        },
                        "body": json.dumps({"errors": ["Invalid presigned URL"]}),
                        "isBase64Encoded": False,
                    }
                )
            print("output_filepath=", output_filepath)
            with open(output_filepath, "rb") as f:
                # 5xx responses are normal for s3, recommendation is to try 10 times
                # https://aws.amazon.com/premiumsupport/knowledge-center/http-5xx-errors-s3/
                attempts = 0
                files = {"file": (output_filepath, f)}
                print(f'splat|posting_to_s3|{presigned_url["url"]}|{presigned_url["fields"].get("key")}')
                while attempts < S3_RETRY_COUNT:
                    response = requests.post(
                        presigned_url["url"], data=presigned_url["fields"], files=files, timeout=60
                    )
                    print(f"splat|s3_response|{response.status_code}")
                    if response.status_code in [500, 503]:
                        attempts += 1
                        print("splat|s3_retry")
                    else:
                        break
                else:
                    print("splat|s3_max_retry_reached")
                    return respond(
                        {
                            "statusCode": response.status_code,
                            "headers": response.headers,
                            "body": response.content,
                            "isBase64Encoded": False,
                        }
                    )
            if response.status_code != 204:
                print(f"splat|presigned_url_save|unknown_error|{response.status_code}|{response.content}")
                return respond(
                    {
                        "statusCode": response.status_code,
                        "headers": response.headers,
                        "body": response.content,
                        "isBase64Encoded": False,
                    }
                )
            else:
                return respond(
                    {
                        "statusCode": 201,
                        "headers": {
                            "Content-Type": "application/json",
                        },
                        "body": "",
                        "isBase64Encoded": False,
                    }
                )

        else:
            print("splat|stream_binary_response")
            # Otherwise just stream the pdf data back.
            with open(output_filepath, "rb") as f:
                binary_data = f.read()
            b64_encoded_pdf = base64.b64encode(binary_data).decode("utf-8")
            # Check size. lambda has a 6mb limit. Check if > 5.5mb
            if sys.getsizeof(b64_encoded_pdf) / 1024 / 1024 > 5.5:
                return respond(
                    {
                        "statusCode": 500,
                        "headers": {
                            "Content-Type": "application/json",
                        },
                        "body": json.dumps(
                            {
                                "errors": [
                                    'The resulting PDF is too large to stream back from lambda. Please use "presigned_url" to upload it to s3 instead.'
                                ]
                            }
                        ),
                        "isBase64Encoded": False,
                    }
                )
            return respond(
                {
                    "statusCode": 200,
                    "headers": {
                        "Content-Type": "application/pdf",
                    },
                    "body": b64_encoded_pdf,
                    "isBase64Encoded": True,
                }
            )

    except NotImplementedError:
        logger.error("splat|not_implemented_error")
        return respond(
            {
                "statusCode": 501,
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": json.dumps({"errors": ["The requested feature is not implemented, yet."]}),
                "isBase64Encoded": False,
            }
        )

    except json.JSONDecodeError as e:
        return respond(
            {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": json.dumps({"errors": [f"Failed to decode request body as JSON: {str(e)}"]}),
                "isBase64Encoded": False,
            }
        )

    except Exception as e:
        logger.error(f"splat|unknown_error|{str(e)}|stacktrace:", exc_info=True)
        return respond(
            {
                "statusCode": 500,
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": json.dumps({"errors": [f"An unknown error occured: {str(e)}"]}),
                "isBase64Encoded": False,
            }
        )


def check_license():
    tree = ET.parse("./prince-engine/license/license.dat")  # noqa
    parsed_license = {child.tag: (child.attrib, child.text) for child in tree.getroot() if child.tag != "signature"}
    is_demo_license = bool(list(filter(lambda x: x[0] == "option" and x[1].get("id") == "demo", parsed_license)))

    return respond(
        {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
            },
            "body": json.dumps({**parsed_license, "is_demo_license": is_demo_license}),
            "isBase64Encoded": False,
        }
    )


if __name__ == "__main__":
    import json
    import sys

    print(lambda_handler({"body": json.dumps({"check_license": True})}, None))
