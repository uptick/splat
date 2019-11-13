import json
import subprocess
import boto3


def pdf_from_html(body_html):
    """
    Uses princexml to render a pdf from html/css/js
    Saves the file at /tmp/output.pdf and returns any stdout from prince.
    """
    # Save body_html to file
    with open('/tmp/input.html', 'w') as f:
        f.write(body_html)
    # Run the prince binary and just see if we get some output
    popen = subprocess.Popen(['./prince/lib/prince/bin/prince', '/tmp/input.html', '-o', '/tmp/output.pdf'], stdout=subprocess.PIPE)
    popen.wait()
    return popen.stdout.read().decode()


def lambda_handler(event, context):
    # Extract html from event
    body_html = event.get('body_html')
    if not body_html:
        return {
            'statusCode': 400,
            'body': 'Please specify body_html',
        }
    output = pdf_from_html(body_html)
    if output:
        return {
            'statusCode': 500,
            'prince_output': output,
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
        elif event.get('presigned_url'):
            presigned_url = event.get('presigned_url')
            raise NotImplementedError()
    return {
        'statusCode': 200,
        's3_object_url': url,
    }
