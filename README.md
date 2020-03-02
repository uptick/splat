# splat
splat is simple aws lambda function that invokes PrinceXML, and a convenient collection of scripts to install it with a sensible API wrapping it.

It is intended to be a DIY docraptor of sorts, and for the most part should be a drop in replacement for PDF generation.

## Installation
The bulk of splat code lives in invoke scripts to create the necessary AWS objects to support it. These assume you have already configured your awscli environment, and will create the objects in the default region.

1. Clone the repo
2. Get a virtual environment `pipenv install`
3. Go in the environment `pipenv shell`
6. Create the lambda function and API with `inv create`. (Append `--no-prince-license` if you do not have a license for prince. See below.)
7. Done. The script will return all relevant information for you to invoke your lambda with all the HTML/CSS/Javascript you want.

If you make changes to the lambda code, run `inv deploy` to update it with everything inside the inner splat directory. No need to re-run the create script.

AWS permissions required to create objects:
- iam: create role
- lambda: create lambda
- apigateway: create apigateway

## PrinceXML License
splat will attempt to install a PrinceXML license file by default. Just drop your `license.dat` in the root directory and run `deploy` or `install`. The licence file is gitignored for your convenience.
If you do not have a licence file, you will need to append `--no-prince-license` to deploy or create. Prince will watermark your PDFs, and you can only use them non-commercially. See their [license page](https://www.princexml.com/purchase/license_faq/) for more information.
