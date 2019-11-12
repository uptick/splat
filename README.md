# How to splat?
1. Clone the repo
2. Get a virtual environment `pipenv install -d`
3. Go in the environment `pipenv shell`
4. Make sure you have your awscli environment set up.
5. Create the lambda function with `inv create` - you will need to supply an existing role ARN for the lambda. This creates the function and API.
6. Done. Invoke your lambda with all the HTML/CSS you want. It'll save the resulting PDF to s3 and return a link to it.

If you make changes to the lambda code, run `inv deploy` to update it with everything inside the inner splat directory.