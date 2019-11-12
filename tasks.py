import os

from invoke import run, task

PRINCE_FILENAME = 'prince-12.5-linux-generic-x86_64'
ZIP_FILENAME = 'splat.zip'


def prompt(message):
    print(message)
    return input()


def create_zip():
    # Download binary if it doesn't exist
    if not os.path.exists(f'{PRINCE_FILENAME}.tar.gz'):
        print('Downloading princeXML...')
        run(f'curl -O -J https://www.princexml.com/download/{PRINCE_FILENAME}.tar.gz')
    print('Extracting...')
    run(f'tar -xf {PRINCE_FILENAME}.tar.gz')
    print('Copying...')
    run(f'cp -r {PRINCE_FILENAME}/lib/prince/ splat/')
    print('Cleaning up...')
    run(f'rm -r {PRINCE_FILENAME}')
    # Zip up project contents
    print('Compressing project...')
    run(f'cd splat && zip -FSrq ../{ZIP_FILENAME} *')


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
    create_zip()
    # Send to aws
    print('Updating lambda...')
    run(f'aws lambda update-function-code --function-name {function_arn} --zip-file fileb://{ZIP_FILENAME}')
    print('Uploading to s3...')
    run(f'aws s3 cp {ZIP_FILENAME} s3://{bucket_name}/{ZIP_FILENAME}')
    print('Done!')


@task
def create(ctx):
    runtime = 'python3.7'
    handler = 'lambda_function.lambda_handler'
    function_name = prompt('function name:')
    role = prompt('role:')
    create_zip()
    command = (
        f'aws lambda create-function '
        f'--function-name {function_name} '
        f'--runtime {runtime} '
        f'--role {role} '
        f'--handler {handler} '
        f'--zip-file fileb://{ZIP_FILENAME} '
    )
    print(command)
    # TODO: Print command and ask user to confirm
    run(command)


@task
def invoke(ctx):
    function_arn = os.getenv('FUNCTION_ARN')
    print('request status:')
    run(f'aws lambda invoke --function-name {function_arn} --invocation-type RequestResponse test.json')
    print('response:')
    run(f'cat test.json && rm test.json')
    print()
