# splat
splat is simple aws lambda function that invokes PrinceXML, and a convenient collection of scripts to install it with a sensible API wrapping it.

It is intended to be a DIY docraptor of sorts, and for the most part should be a drop in replacement for PDF generation.

## Installation
The bulk of splat code lives in invoke scripts to create the necessary AWS objects to support it. These assume you have already configured your awscli environment, and will create the objects in the default region.

1. Clone the repo
2. Get a virtual environment `pipenv install -d`
3. Go in the environment `pipenv shell`
6. Create the lambda function and API with `inv create`.
7. Done. The script will return all relevant information for you to invoke your lambda with all the HTML/CSS/Javascript you want.

If you make changes to the lambda code, run `inv deploy` to update it with everything inside the inner splat directory. No need to re-run the create script.

AWS permissions required to create objects:
- iam: create role
- lambda: create lambda
- apigateway: create apigateway