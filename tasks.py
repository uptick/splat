import json
import os

from invoke import run, task

PRINCE_FILENAME = 'prince-12.5-linux-generic-x86_64'
ZIP_FILENAME = 'splat.zip'
FUNCTION_NAME = 'splat2'


def prompt(message):
    print(message)
    return input()


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
    # Zip up project contents
    print('Compressing project...')
    run(f'cd splat && zip -FSrq ../{ZIP_FILENAME} *')


@task
def setup(ctx):
    function_arn = prompt('FUNCTION_ARN')
    with open('.envrc', 'w') as f:
        f.write(
            f'export FUNCTION_ARN={function_arn}\n'
            )
    print('done - please source .envrc with ". .envrc"')


@task
def deploy(ctx):
    create_zip()
    # Send to aws
    print('Updating lambda...')
    run(f'aws lambda update-function-code --function-name {FUNCTION_NAME} --zip-file fileb://{ZIP_FILENAME}')
    print('Done!')


@task
def create(ctx):
    runtime = 'python3.7'
    handler = 'lambda_function.lambda_handler'
    role = prompt('lambda role ARN:')
    create_zip()

    # Create lambda
    command = (
        'aws lambda create-function '
        f'--function-name {FUNCTION_NAME} '
        f'--runtime {runtime} '
        f'--role {role} '
        f'--handler {handler} '
        f'--zip-file fileb://{ZIP_FILENAME} '
    )
    print(command)
    output = json.loads(run(command).stdout)
    lambda_arn = output['FunctionArn']
    region = lambda_arn.split(':')[3]
    account_id = lambda_arn.split(':')[4]

    # Create API
    command = (
        'aws apigateway create-rest-api '
        f'--name {FUNCTION_NAME}-api '
    )
    print(command)
    output = json.loads(run(command).stdout)
    api_id = output['id']
    api_root_id = json.loads(run(f'aws apigateway get-resources --rest-api-id {api_id}').stdout)['items'][0]['id']

    # Create POST method on /
    command = (
        'aws apigateway put-method '
        f'--rest-api-id {api_id} '
        f'--resource-id {api_root_id} '
        '--http-method POST '
        '--authorization-type NONE '
    )
    print(command)
    run(command)

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
    print(command)
    run(command)

    # Set API response type to JSON
    command = (
        'aws apigateway put-method-response '
        f'--rest-api-id {api_id} '
        f'--resource-id {api_root_id} '
        '--http-method POST '
        '--status-code 200 '
        '--response-models application/json=Empty '
    )
    print(command)
    run(command)

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
    print(command)
    run(command)

    # Deploy the API
    command = (
        'aws apigateway create-deployment '
        f'--rest-api-id {api_id} '
        '--stage-name prod '
    )
    print(command)
    run(command)

    # Create usage plan
    command = (
        'aws apigateway create-usage-plan '
        f'--name {FUNCTION_NAME}-usageplan '
        f'--api-stages apiId={api_id},stage=prod '
    )
    print(command)
    output = json.loads(run(command).stdout)
    usage_plan_id = output['id']

    # Create API key
    command = (
        'aws apigateway create-api-key '
        f'--name {FUNCTION_NAME}-key '
        '--enabled '
    )
    print(command)
    output = json.loads(run(command).stdout)
    api_key = output['value']
    api_key_id = output['id']

    # Enable the API key for the usage plan
    command = (
        'aws apigateway create-usage-plan-key '
        f'--usage-plan-id {usage_plan_id} '
        f'--key-id {api_key_id} '
        '--key-type API_KEY '
    )
    print(command)
    run(command)

    # Grant invoke permissions to the API
    command = (
        'aws lambda add-permission '
        f'--function-name {FUNCTION_NAME} '
        f'--statement-id {FUNCTION_NAME}-test '
        '--action lambda:InvokeFunction '
        '--principal apigateway.amazonaws.com '
        f'--source-arn "arn:aws:execute-api:{region}:{account_id}:{api_id}/*/POST/" '
    )
    print(command)
    run(command)
    command = (
        'aws lambda add-permission '
        f'--function-name {FUNCTION_NAME} '
        f'--statement-id {FUNCTION_NAME}-prod '
        '--action lambda:InvokeFunction '
        '--principal apigateway.amazonaws.com '
        f'--source-arn "arn:aws:execute-api:{region}:{account_id}:{api_id}/prod/POST/" '
    )
    print(command)
    run(command)

    print('Done!')
    print(f'API Key: {api_key}')
    print(f'API URL: https://{api_id}.execute-api.{region}.amazonaws.com/prod')
