# How to splat?
1. Clone the repo
2. Get a virtual environment `pipenv install -d`
3. Go in the environment `pipenv shell`
4. Create the lambda function with `inv create`
5. Enter the details it asks you (function name and role); the role needs to exist in aws already.
6. Generate your secret file with `inv setup` - enter the details it asks you (currently just the ARN of the function)
7. Deploy the code to your new function with `inv deploy`. It'll download prince and send it all up to your lambda.
8. Done. Invoke your lambda with all the HTML/CSS you want. It'll save the resulting PDF to s3 and return a link to it.
