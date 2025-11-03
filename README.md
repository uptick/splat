# splat

splat is simple aws lambda function that takes HTML/CSS/JS, invokes PrinceXML to render it and returns the resulting PDF in one of many ways.

It is intended to be a DIY docraptor of sorts.

## Installation

Simply build the docker image, deploy it to AWS, then invoke the lambda with an event body JSON that performs the desired operation. For example: `{"document_content": "<h1>Hello, World!</h1>"}`

This can be done via a function_url, apigateway or lambda invoke.

## Invoking splat

Event payload body.

| Field                      | Type                        | Description                                                                                                                                                                         |
|----------------------------|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **javascript (princexml)** | boolean (False)             | Enables [princeXML's javascript execution](https://www.princexml.com/doc/javascript/). This will not render react but can be used for formatting.                                   |
| **check_license**          | boolean (False)             | Send this field to receive a check on remaining license usage                                                                                                                       |
| **document_content**       | string                      | Embed the html content in the payload. There will be AWS payload size limitations.                                                                                                  |
| **document_url**           | url                         | Fetch the html content from `document_url` to disk before rendering.                                                                                                                |
| **browser_url**            | url                         | Browser the `browser_url` with `playwright` before rendering with `renderer`                                                                                                        |
| **browser_headers**        | Mapping[str,str]            | Add additional headers to playwright before visiting `browser_url`                                                                                                                  |
| **browser_pdf_options**    | Mapping[str,str]            | Add additional options to playwright `.pdf()` call                                                                                                                                  |                                                                                                                                                                           |
| **renderer**               | `princexml` or `playwright` | Renderer to render the html with                                                                                                                                                    |
| **bucket_name**            | string                      | Output the resulting pdf to `s3://{bucket_name}/{uuid}.pdf`. The lambda will require permission to upload to the bucket. The response will include `bucket`, `key`, `presigned_url` |
| **presigned_url**          | url                         | Output the resulting pdf to the presigned url. Generate the presigned url with `put_object`. See Output for more information.                                                       |

### Input

Pass content in event: `{"document_content": "<h1>Hello, World!</h1>"}`

Pass content via URL: `{"document_url": "https://some_page/report.html"}`

Pass content via Browser page: `{"browser_url": "https://some_react_page/", "renderer": "princexml", "browser_headers": {"Authorization": "Bearer SOME_BEARER_TOKEN"}}`

### Output

Returns PDF base64 encoded by default.

To save to an s3 bucket (lambda requires permission): `{"bucket_name": "<BUCKET>"}`

To save to a presigned url: `{"presigned_url": "<URL>"}`

## PrinceXML License

splat will attempt to install a PrinceXML license file by default. Just drop your `license.dat` in the root directory before you build the docker container. The licence file is gitignored for your convenience.
If you do not have a licence file, Prince will watermark your PDFs, and you can only use them non-commercially. See their [license page](https://www.princexml.com/purchase/license_faq/) for more information.

You can check the status of the licence by invoking the lambda with the `{"check_license": true}` option, and interpreting the response, you can use this to periodically check the status of the licence and raise an alert if it's about to expire, and to verify that your new licence has updated correctly.

## Fonts

splat will add any fonts inside a `fonts.zip` file. Ensure the zip file contains a folder called `fonts` with all fonts inside. Simply drop into the root directory and build the docker container. The `fonts.zip` file is gitignored for your convenience. By default, prince comes with a small suite of liberation fonts.

## Library

Splat can be used via the `uptick_splat` library. Install with `pip install uptick_splat`.

Usage:

```python
from uptick_splat import configure_splat, pdf_with_splat


configure_splat(
    function_region="ap-southeast-2",
    function_name="splat",
    default_bucket_name="your-bucket-to-upload-html-to",
)

some_html = "<h1>test</h1>"

pdf_with_splat(some_html, bucket_name="test_bucket")
# or
pdf_with_splat(some_html)
```

# Development

Install [mise](https://mise.jdx.dev/getting-started.html) task runner.


```
mise run install # booststrap the project and install requirements

mise run test # run tests

mise run format # format
```

## Local testing

Use the `./splat_cli.py` program (via UV) to execute the lambda.
It is possible to target the lambda running in the docker container or a deployed lambda running in aws.

Example usages:

```bash
# Invoke using a local function url
./splat_cli.py -o /tmp/google.pdf -b https://google.com

# Invoke using a deployed AWS lambda against an embedded document content
./splat_cli.py -o /tmp/test.pdf -c "<h1> hi </h1>" --function-name splat-staging

```
