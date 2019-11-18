import json
import subprocess
import boto3
import base64


def pdf_from_string(document_content, javascript=False):
    # Save document_content to file
    with open('/tmp/input.html', 'w') as f:
        f.write(document_content)
    return prince_handler('/tmp/input.html')


def pdf_from_url(document_url, javascript=False):
    # Fetch URL and save to file
    raise NotImplementedError()


def prince_handler(input_filepath, output_filepath='/tmp/output.pdf', javascript=False,):
    command = ['./prince/lib/prince/bin/prince', input_filepath, '-o', output_filepath]
    if javascript:
        command.append('--javascript')
    popen = subprocess.Popen(command, stdout=subprocess.PIPE)
    popen.wait()
    # TODO: Handle prince errors, stdout, stderr, catch exceptions
    # stdout = popen.stdout.read().decode()
    return output_filepath


# Entrypoint for AWS
def lambda_handler(event, context):
    javascript = bool(event.get('javascript', False))
    # Create PDF
    if event.get('document_content'):
        output_filepath = pdf_from_string(event.get('document_content'), javascript)
    elif event.get('document_url'):
        output_filepath = pdf_from_url(event.get('document_url'), javascript)
    else:
        return {
            'statusCode': 400,
            'headers': {
                'content-type': 'application/json',
            },
            'body': json.dumps({'errors': ['Please specify either "document_content" or "document_url"']}),
            'isBase64Encoded': False,
        }

    # Return PDF
    if event.get('bucket_name'):
        # Upload to s3 and return URL
        bucket_name = event.get('bucket_name')
        key = 'output.pdf'
        s3 = boto3.resource('s3')
        bucket = s3.Bucket(bucket_name)
        bucket.upload_file('/tmp/output.pdf', key)
        location = boto3.client('s3').get_bucket_location(Bucket=bucket_name)['LocationConstraint']
        url = f'https://{bucket_name}.s3-{location}.amazonaws.com/{key}'

        return {
            'statusCode': 200,
            'headers': {
                'content-type': 'application/json',
            },
            'body': json.dumps({'url': url}),
            'isBase64Encoded': False,
        }
    elif event.get('presigned_url'):
        raise NotImplementedError()
    else:
        # Otherwise just stream the pdf data back.
        with open(output_filepath, 'rb') as f:
            binary_data = f.read()

        return base64.b64encode(binary_data).decode()
