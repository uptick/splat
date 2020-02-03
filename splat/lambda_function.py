import base64
import json
import os
import subprocess
from urllib.parse import urlparse

import boto3
import requests


def init():
    os.environ['FONTCONFIG_PATH'] = '/var/task/fonts'


def pdf_from_string(document_content, javascript=False):
    print("splat|pdf_from_string")
    # Save document_content to file
    with open('/tmp/input.html', 'w') as f:
        f.write(document_content)
    return prince_handler('/tmp/input.html', javascript=javascript)


def pdf_from_url(document_url, javascript=False):
    print("splat|pdf_from_url")
    # Fetch URL and save to file
    raise NotImplementedError()


def execute(cmd):
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True)
    for stdout_line in iter(popen.stdout.readline, ""):
        yield stdout_line
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)


def prince_handler(input_filepath, output_filepath='/tmp/output.pdf', javascript=False):
    print("splat|prince_command_run")
    # Prepare command
    command = [
        './prince/lib/prince/bin/prince',
        input_filepath,
        '-o',
        output_filepath,
        '--structured-log=normal',
        '--verbose',
    ]
    if javascript:
        command.append('--javascript')
    # Run command and capture output
    print(f"splat|invoke_prince {' '.join(command)}")
    try:
        for stdout_line in execute(command):
            print(stdout_line, end="")
    except subprocess.CalledProcessError as e:
        print(f"splat|calledProcessError|{str(e)}")
    # Log prince output
    return output_filepath


# Entrypoint for AWS
def lambda_handler(event, context):
    try:
        print("splat|begin")
        init()
        # Parse payload - assumes json
        body = json.loads(event.get('body'))
        javascript = bool(body.get('javascript', False))
        print(f"splat|javascript={javascript}")
        # Create PDF
        if body.get('document_content'):
            output_filepath = pdf_from_string(body.get('document_content'), javascript)
        elif body.get('document_url'):
            output_filepath = pdf_from_url(body.get('document_url'), javascript)
        else:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                },
                'body': json.dumps({'errors': ['Please specify either document_content or document_url']}),
                'isBase64Encoded': False,
            }

        # Return PDF
        if body.get('bucket_name'):
            print('splat|bucket_save')
            # Upload to s3 and return URL
            bucket_name = body.get('bucket_name')
            key = 'output.pdf'
            s3 = boto3.resource('s3')
            bucket = s3.Bucket(bucket_name)
            bucket.upload_file('/tmp/output.pdf', key)
            location = boto3.client('s3').get_bucket_location(Bucket=bucket_name)['LocationConstraint']
            url = f'https://{bucket_name}.s3-{location}.amazonaws.com/{key}'

            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                },
                'body': json.dumps({'url': url}),
                'isBase64Encoded': False,
            }
        elif body.get('presigned_url'):
            print('splat|presigned_url_save')
            presigned_url = body.get('presigned_url')
            if not urlparse(presigned_url['url']).netloc.endswith('amazonaws.com'):
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                    },
                    'body': json.dumps({'errors': ['Invalid presigned URL']}),
                    'isBase64Encoded': False,
                }
            with open(output_filepath, 'rb') as f:
                files = {'file': (output_filepath, f)}
                print('splat|posting_to_s3')
                response = requests.post(
                    presigned_url['url'],
                    data=presigned_url['fields'],
                    files=files
                )
                print(f'splat|response|{response.content}')
            if response.status_code != 204:
                return {
                    'statusCode': response.status_code,
                    'headers': response.headers,
                    'body': response.content,
                    'isBase64Encoded': False,
                }
            else:
                return {
                    'statusCode': 201,
                    'headers': {
                        'Content-Type': 'application/json',
                    },
                    'body': '',
                    'isBase64Encoded': False,
                }

        else:
            print('splat|stream_binary_response')
            # Otherwise just stream the pdf data back.
            with open(output_filepath, 'rb') as f:
                binary_data = f.read()

            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/pdf',
                },
                'body': base64.b64encode(binary_data).decode('utf-8'),
                'isBase64Encoded': True,
            }

    except NotImplementedError:
        print('splat|not_implemented_error')
        return {
            'statusCode': 501,
            'headers': {
                'Content-Type': 'application/json',
            },
            'body': json.dumps({'errors': ['The requested feature is not implemented, yet.']}),
            'isBase64Encoded': False,
        }

    except json.JSONDecodeError as e:
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
            },
            'body': json.dumps({'errors': [f'Failed to decode request body as JSON: {str(e)}']}),
            'isBase64Encoded': False,
        }

    except Exception as e:
        print(f'splat|unknown_error|{str(e)}')
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
            },
            'body': json.dumps({'errors': [f'An unknown error occured: {str(e)}']}),
            'isBase64Encoded': False,
        }
