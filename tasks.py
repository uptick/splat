import json
import os
from pprint import pprint
from time import sleep

import boto3
from invoke import run, task

PRINCE_FILENAME = 'prince-13.1-linux-generic-x86_64'
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
    print('Removing old prince...')
    run(f'rm -rf splat/prince/')
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
    lambda_client = boto3.client('lambda')
    with open(ZIP_FILENAME, 'rb') as zipfile:
        response = lambda_client.update_function_code(
            FunctionName=FUNCTION_NAME,
            ZipFile=zipfile.read(),
        )
    print('Done!')
    pprint(response)


@task
def create(ctx):
    # TODO: Print AWS region info + confirm?
    create_zip()

    print("Obtaining clients...")
    iam_client = boto3.client('iam')
    lambda_client = boto3.client('lambda')
    apigateway_client = boto3.client('apigateway')

    print("Creating role...")
    result = iam_client.create_role(
        RoleName=f'{FUNCTION_NAME}-role',
        AssumeRolePolicyDocument='{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}',
    )
    role_arn = result['Role']['Arn']
    role_name = result['Role']['RoleName']

    print("Attaching policy to role...")
    result = iam_client.attach_role_policy(
        RoleName=role_name,
        PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
    )

    print("Creating lambda...")
    attempts = 0
    while True:
        try:
            with open(ZIP_FILENAME, 'rb') as zipfile:
                result = lambda_client.create_function(
                    FunctionName=FUNCTION_NAME,
                    Runtime='python3.8',
                    Role=role_arn,
                    Handler='lambda_function.lambda_handler',
                    Code={'ZipFile': zipfile.read()},
                )
            break
        except lambda_client.exceptions.InvalidParameterValueException:
            attempts += 1
            print("Failed. Probably role replication. Trying again.")
            if attempts > 5:
                raise Exception(f"Failed to create lambda after {attempts} attempts. The role takes a while to replicate, but not usually this long...")
            sleep(5)

    lambda_arn = result['FunctionArn']
    region = lambda_arn.split(':')[3]
    account_id = lambda_arn.split(':')[4]

    print("Creating API...")
    result = apigateway_client.create_rest_api(
        name=f'{FUNCTION_NAME}-api',
        binaryMediaTypes=['application/pdf']
    )
    api_id = result['id']

    print("Getting API root ID...")
    result = apigateway_client.get_resources(
        restApiId=api_id,
    )
    api_root_id = result['items'][0]['id']

    print("Create post method on /")
    apigateway_client.put_method(
        restApiId=api_id,
        resourceId=api_root_id,
        httpMethod='POST',
        authorizationType='NONE',
        apiKeyRequired=True,
    )

    print("Set lambda proxy as the integration...")
    uri = f'arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions/arn:aws:lambda:{region}:{account_id}:function:{FUNCTION_NAME}/invocations'
    apigateway_client.put_integration(
        restApiId=api_id,
        resourceId=api_root_id,
        httpMethod='POST',
        type='AWS_PROXY',
        integrationHttpMethod='POST',
        uri=uri,
    )

    print("Deploy the API...")
    apigateway_client.create_deployment(
        restApiId=api_id,
        stageName='prod',
    )

    print("Create usage plan...")
    result = apigateway_client.create_usage_plan(
        name=f'{FUNCTION_NAME}-usageplan',
        apiStages=[{'apiId': api_id, 'stage': 'prod'}]
    )
    usage_plan_id = result['id']

    print("Create API key...")
    result = apigateway_client.create_api_key(
        name=f'{FUNCTION_NAME}-key',
        enabled=True,
    )
    api_key = result['value']
    api_key_id = result['id']

    print("Enable the API key for the usage plan...")
    apigateway_client.create_usage_plan_key(
        usagePlanId=usage_plan_id,
        keyId=api_key_id,
        keyType='API_KEY',
    )

    print("Grant invoke permissions to the API")
    lambda_client.add_permission(
        FunctionName=FUNCTION_NAME,
        StatementId=f'{FUNCTION_NAME}-prod',
        Action='lambda:InvokeFunction',
        Principal='apigateway.amazonaws.com',
        SourceArn=f'arn:aws:execute-api:{region}:{account_id}:{api_id}/*/POST/',
    )

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
