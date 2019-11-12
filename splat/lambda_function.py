import json
import subprocess


def lambda_handler(event, context):
    # Run the prince binary and just see if we get some output
    popen = subprocess.Popen(['./prince/bin/prince'], stdout=subprocess.PIPE)
    popen.wait()
    output = popen.stdout.read().decode()
    return {
        'statusCode': 200,
        'body': json.dumps(output),
    }
