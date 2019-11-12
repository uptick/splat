import os

from invoke import run, task


def prompt(message):
    print(message)
    return input()


@task
def setup(ctx):
    function_arn = prompt('FUNCTION_ARN')
    bucket_name = prompt('BUCKET_NAME')
    with open('.envrc', 'w') as f:
        f.write(
            f'export FUNCTION_ARN={function_arn}\n'
            f'export BUCKET_NAME={bucket_name}\n'
            )
    print('done - please source .envrc with ". .envrc"')


@task
def deploy(ctx):
    function_arn = os.getenv('FUNCTION_ARN')
    bucket_name = os.getenv('BUCKET_NAME')
    # Zip up project contents
    run(f'cd html2pdf && zip -FSr ../html2pdf.zip *')
    # Send to aws
    run(f'aws lambda update-function-code --function-name {function_arn} --zip-file fileb://html2pdf.zip')
    run(f'aws s3 cp html2pdf.zip s3://{bucket_name}/html2pdf.zip')
