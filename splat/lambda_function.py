import base64
import json
import os
import subprocess
import sys
from itertools import chain
from urllib.parse import urlparse
from uuid import uuid4

import boto3
import requests


S3_RETRY_COUNT = 10


def init():
    # If there's any files in the font directory, export FONTCONFIG_PATH
    if any(f for f in os.listdir('fonts') if f != 'fonts.conf'):
        os.environ['FONTCONFIG_PATH'] = '/var/task/fonts'


def cleanup():
    command = ['rm', '/tmp/*.html', '/tmp/*.pdf']
    try:
        for line in execute(command):
            print("splat|cleanup|", line, end="")
    except subprocess.CalledProcessError:
        pass


def pdf_from_string(document_content, javascript=False):
    print("splat|pdf_from_string")
    # Save document_content to file
    with open('/tmp/input.html', 'w') as f:
        f.write(document_content)
    return prince_handler('/tmp/input.html', javascript=javascript)


def pdf_from_url(document_url, javascript=False):
    print("splat|pdf_from_url")
    # Fetch URL and save to file
    raise NotImplementedError("Saving from URL is not yet supported.")


def execute(cmd):
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    for line in chain(iter(popen.stdout.readline, ""), iter(popen.stderr.readline, "")):
        yield line
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)


def execute_shell(cmd):
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, shell=True)
    for line in chain(iter(popen.stdout.readline, ""), iter(popen.stderr.readline, "")):
        yield line
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)


def prince_handler(input_filepath, output_filepath=None, javascript=False):
    if not output_filepath:
        output_filepath = f'/tmp/{uuid4()}.pdf'
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
    for line in execute(command):
        print("splat|prince_output|", line, end="")
    # Log prince output
    return output_filepath


def respond(payload):
    cleanup()
    return payload


def debug_no_space():
    commands = [
        'ls -alhS',
        'du -sh *',
        'ls -alhS /tmp',
        'du -sh /tmp/*',
    ]
    for command in commands:
        try:
            for line in execute_shell(command):
                print(f"splat|debug|{command}|", line, end="")
        except subprocess.CalledProcessError:
            pass


# Entrypoint for AWS
def lambda_handler(event, context):
    try:
        print("splat|begin")
        debug_no_space()
        init()
        # Parse payload - assumes json
        body = json.loads(event.get('body'))
        javascript = bool(body.get('javascript', False))
        print(f"splat|javascript={javascript}")
        # Create PDF
        try:
            if body.get('document_content'):
                output_filepath = pdf_from_string(body.get('document_content'), javascript)
            elif body.get('document_url'):
                output_filepath = pdf_from_url(body.get('document_url'), javascript)
            else:
                return respond({
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                    },
                    'body': json.dumps({'errors': ['Please specify either document_content or document_url']}),
                    'isBase64Encoded': False,
                })
        except subprocess.CalledProcessError as e:
            print(f"splat|calledProcessError|{str(e)}")
            return respond({
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'application/json',
                },
                'body': json.dumps({'errors': [str(e)]}),
                'isBase64Encoded': False,
            })

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

            return respond({
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                },
                'body': json.dumps({'url': url}),
                'isBase64Encoded': False,
            })
        elif body.get('presigned_url'):
            print('splat|presigned_url_save')
            presigned_url = body.get('presigned_url')
            if not urlparse(presigned_url['url']).netloc.endswith('amazonaws.com'):
                return respond({
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                    },
                    'body': json.dumps({'errors': ['Invalid presigned URL']}),
                    'isBase64Encoded': False,
                })
            with open(output_filepath, 'rb') as f:
                # 5xx responses are normal for s3, recommendation is to try 10 times
                # https://aws.amazon.com/premiumsupport/knowledge-center/http-5xx-errors-s3/
                attempts = 0
                files = {'file': (output_filepath, f)}
                print(f'splat|posting_to_s3|{presigned_url["url"]}|{presigned_url["fields"].get("key")}')
                while attempts < S3_RETRY_COUNT:
                    response = requests.post(
                        presigned_url['url'],
                        data=presigned_url['fields'],
                        files=files
                    )
                    print(f'splat|s3_response|{response.status_code}')
                    if response.status_code in [500, 503]:
                        attempts += 1
                        print('splat|s3_retry')
                    else:
                        break
                else:
                    print('splat|s3_max_retry_reached')
                    return respond({
                        'statusCode': response.status_code,
                        'headers': response.headers,
                        'body': response.content,
                        'isBase64Encoded': False,
                    })
            if response.status_code != 204:
                print(f'splat|presigned_url_save|unknown_error|{response.status_code}|{response.content}')
                return respond({
                    'statusCode': response.status_code,
                    'headers': response.headers,
                    'body': response.content,
                    'isBase64Encoded': False,
                })
            else:
                return respond({
                    'statusCode': 201,
                    'headers': {
                        'Content-Type': 'application/json',
                    },
                    'body': '',
                    'isBase64Encoded': False,
                })

        else:
            print('splat|stream_binary_response')
            # Otherwise just stream the pdf data back.
            with open(output_filepath, 'rb') as f:
                binary_data = f.read()
            b64_encoded_pdf = base64.b64encode(binary_data).decode('utf-8')
            # Check size. lambda has a 6mb limit. Check if > 5.5mb
            if sys.getsizeof(b64_encoded_pdf) / 1024 / 1024 > 5.5:
                return respond({
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                    },
                    'body': json.dumps({'errors': ['The resulting PDF is too large to stream back from lambda. Please use "presigned_url" to upload it to s3 instead.']}),
                    'isBase64Encoded': False,
                })
            return respond({
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/pdf',
                },
                'body': b64_encoded_pdf,
                'isBase64Encoded': True,
            })

    except NotImplementedError:
        print('splat|not_implemented_error')
        return respond({
            'statusCode': 501,
            'headers': {
                'Content-Type': 'application/json',
            },
            'body': json.dumps({'errors': ['The requested feature is not implemented, yet.']}),
            'isBase64Encoded': False,
        })

    except json.JSONDecodeError as e:
        return respond({
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
            },
            'body': json.dumps({'errors': [f'Failed to decode request body as JSON: {str(e)}']}),
            'isBase64Encoded': False,
        })

    except Exception as e:
        print(f'splat|unknown_error|{str(e)}')
        return respond({
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
            },
            'body': json.dumps({'errors': [f'An unknown error occured: {str(e)}']}),
            'isBase64Encoded': False,
        })
