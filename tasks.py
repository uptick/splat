import json
import os
import time

from invoke import run, task
from invoke.exceptions import UnexpectedExit

PRINCE_FILENAME = 'prince-12.5-linux-generic-x86_64'
ZIP_FILENAME = 'splat.zip'
FUNCTION_NAME = 'splat'


def create_zip():
    # Download binary if it doesn't exist
    if not os.path.exists(f'{PRINCE_FILENAME}.tar.gz'):
        print('Downloading princeXML...')
        run(f'curl -O -J https://www.princexml.com/download/{PRINCE_FILENAME}.tar.gz')
    else:
        print('Using existing princeXML download')
    print('Extracting...')
    run(f'tar -xf {PRINCE_FILENAME}.tar.gz')
    print('Copying files around...')
    run('mkdir -p splat/prince/bin')
    run(f'cp -r {PRINCE_FILENAME}/lib/ splat/prince/')
    print('Cleaning up...')
    run(f'rm -r {PRINCE_FILENAME}')
    # Copy license file, if exists
    if os.path.exists('license.dat'):
        print('Copying license file...')
        run(f'cp license.dat splat/prince/lib/prince/license/')
    # Zip up project contents
    print('Compressing project...')
    run(f'cd splat && zip -FSrq ../{ZIP_FILENAME} *')


def run_aws_command(command, output=True):
    # Runs an aws command using invoke.run and returns a dict of the output
    print(f'Running {command}')
    if not output:
        run(command)
        return
    return json.loads(run(command).stdout)


@task
def deploy(ctx):
    create_zip()
    # Send to aws
    print('Updating lambda...')
    run(f'aws lambda update-function-code --function-name {FUNCTION_NAME} --zip-file fileb://{ZIP_FILENAME}')
    print('Done!')


@task
def create(ctx):
    create_zip()
    # Create role
    command = (
        'aws iam create-role '
        f'--role-name {FUNCTION_NAME}-role '
        '--assume-role-policy-document \'{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}\''
    )
    output = run_aws_command(command)
    role_arn = output['Role']['Arn']
    role_name = output['Role']['RoleName']

    # Attach policy to role
    command = (
        'aws iam attach-role-policy '
        f'--role-name {role_name} '
        '--policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole '
    )
    run_aws_command(command, output=False)

    # It can take a few seconds for AWS to replicate the role through all regions, so the lambda creation can fail
    # Just keep trying until it goes through.

    # Create lambda
    command = (
        'aws lambda create-function '
        f'--function-name {FUNCTION_NAME} '
        f'--runtime python3.7 '
        f'--role {role_arn} '
        f'--handler lambda_function.lambda_handler '
        f'--zip-file fileb://{ZIP_FILENAME} '
    )
    lambda_created = False
    attempts = 0
    while not lambda_created:
        try:
            output = run_aws_command(command)
            lambda_created = True
        except UnexpectedExit as e:
            print('lambda creation failed, waiting on role to be available...')
            attempts += 1
            if attempts >= 5:
                raise Exception(f"Lambda creation failed: {e}")
            time.sleep(3)

    lambda_arn = output['FunctionArn']
    region = lambda_arn.split(':')[3]
    account_id = lambda_arn.split(':')[4]

    # Create API
    command = (
        'aws apigateway create-rest-api '
        f'--name {FUNCTION_NAME}-api '
    )
    output = run_aws_command(command)
    api_id = output['id']
    api_root_id = run_aws_command(f'aws apigateway get-resources --rest-api-id {api_id}')['items'][0]['id']

    # Create POST method on /
    command = (
        'aws apigateway put-method '
        f'--rest-api-id {api_id} '
        f'--resource-id {api_root_id} '
        '--http-method POST '
        '--authorization-type NONE '
    )
    run_aws_command(command)

    # Set our lambda as the destination of the POST method
    uri = f'arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions/arn:aws:lambda:{region}:{account_id}:function:{FUNCTION_NAME}/invocations'
    command = (
        'aws apigateway put-integration '
        f'--rest-api-id {api_id} '
        f'--resource-id {api_root_id} '
        '--http-method POST '
        '--type AWS '
        '--integration-http-method POST '
        f'--uri {uri} '
    )
    run_aws_command(command)

    # Set API response type to JSON
    command = (
        'aws apigateway put-method-response '
        f'--rest-api-id {api_id} '
        f'--resource-id {api_root_id} '
        '--http-method POST '
        '--status-code 200 '
        '--response-models application/json=Empty '
    )
    run_aws_command(command)

    # Set lambda response type to JSON
    command = (
        'aws apigateway put-integration-response '
        f'--rest-api-id {api_id} '
        f'--resource-id {api_root_id} '
        '--http-method POST '
        '--status-code 200 '
        '--response-templates application/json="" '
        '--content-handling CONVERT_TO_BINARY '
    )
    run_aws_command(command)

    # Deploy the API
    command = (
        'aws apigateway create-deployment '
        f'--rest-api-id {api_id} '
        '--stage-name prod '
    )
    run_aws_command(command)

    # Create usage plan
    command = (
        'aws apigateway create-usage-plan '
        f'--name {FUNCTION_NAME}-usageplan '
        f'--api-stages apiId={api_id},stage=prod '
    )
    output = run_aws_command(command)
    usage_plan_id = output['id']

    # Create API key
    command = (
        'aws apigateway create-api-key '
        f'--name {FUNCTION_NAME}-key '
        '--enabled '
    )
    output = run_aws_command(command)
    api_key = output['value']
    api_key_id = output['id']

    # Enable the API key for the usage plan
    command = (
        'aws apigateway create-usage-plan-key '
        f'--usage-plan-id {usage_plan_id} '
        f'--key-id {api_key_id} '
        '--key-type API_KEY '
    )
    run_aws_command(command)

    # Grant invoke permissions to the API
    command = (
        'aws lambda add-permission '
        f'--function-name {FUNCTION_NAME} '
        f'--statement-id {FUNCTION_NAME}-test '
        '--action lambda:InvokeFunction '
        '--principal apigateway.amazonaws.com '
        f'--source-arn "arn:aws:execute-api:{region}:{account_id}:{api_id}/*/POST/" '
    )
    run_aws_command(command)
    command = (
        'aws lambda add-permission '
        f'--function-name {FUNCTION_NAME} '
        f'--statement-id {FUNCTION_NAME}-prod '
        '--action lambda:InvokeFunction '
        '--principal apigateway.amazonaws.com '
        f'--source-arn "arn:aws:execute-api:{region}:{account_id}:{api_id}/prod/POST/" '
    )
    run_aws_command(command)

    api_url = f'https://{api_id}.execute-api.{region}.amazonaws.com/prod'

    print('Done!')
    print(f'API Key: {api_key}')
    print(f'API URL: {api_url}')
    print('Test command:')
    print(
        'curl -X POST -k '
        '-H "Accept: application/pdf" '
        '-H "Content-Type: application/json" '
        f'-H "X-API-Key: {api_key}" '
        f'-i "{api_url}" '
        '--data \'{"document_content": "<h1>Hello world!</h1>"}\' > test.pdf'
    )
