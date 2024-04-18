# splat

splat is simple aws lambda function that takes HTML/CSS/JS, invokes PrinceXML to render it and returns the resulting PDF in one of many ways.

It is intended to be a DIY docraptor of sorts.

## Installation

Simply build the docker image, deploy it to AWS, then invoke the lambda with an event body JSON that performs the desired operation. For example: `{"document_content": "<h1>Hello, World!</h1>"}`

## Ways of invoking splat

### Input

Pass content in event: `{"document_content": "<h1>Hello, World!</h1>"}`
Pass content via URL: `{"doucment_url": "<h1>Hello, World!</h1>"}`

### Output

Returns PDF base64 encoded by default.
To save to an s3 bucket (lambda requires permission): `{"bucket_name": "<BUCKET>"}`
To save to a presigned url: `{"presigned_url": "<URL>"}`

### Options

To enable Javascript: `{"javascript": true}`

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
