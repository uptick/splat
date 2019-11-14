import json
import subprocess
import boto3
import base64


def pdf_from_html(body_html, javascript=True):
    """
    Uses princexml to render a pdf from html/css/js
    Saves the file at /tmp/output.pdf and returns any stdout from prince.
    """
    # Save body_html to file
    with open('/tmp/input.html', 'w') as f:
        f.write(body_html)
    # Run the prince binary and just see if we get some output
    command = ['./prince/lib/prince/bin/prince', '/tmp/input.html', '-o', '/tmp/output.pdf']
    if javascript:
        command.append('--javascript')
    popen = subprocess.Popen(, stdout=subprocess.PIPE)
    popen.wait()
    return popen.stdout.read().decode()


def lambda_handler(event, context):
    # Extract html from event
    body_html = event.get('body_html')
    javascript = bool(event.get('javascript', True))
    if not body_html:
        return {
            'statusCode': 400,
            'headers': {
                'content-type': 'application/json',
            },
            'body': json.dumps({'errors': ['Please specify body_html'], 'event': event}),
            'isBase64Encoded': False,
        }
    output = pdf_from_html(body_html)
    if output:
        return {
            'statusCode': 500,
            'headers': {
                'content-type': 'application/json',
            },
            'body': json.dumps({'errors': [output]}),
            'isBase64Encoded': False,
        }
    else:
        # Choose a method for uploading, either direct or presigned
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
            presigned_url = event.get('presigned_url')
            raise NotImplementedError()
        else:
            # Otherwise just stream the pdf data back.
            with open('/tmp/output.pdf', 'rb') as f:
                binary_data = f.read()

            return base64.b64encode(binary_data).decode()

    return {
        'statusCode': 200,
        's3_object_url': url,
    }
