# How to splat?
1. Clone the repo
2. Get a virtual environment `pipenv install -d`
3. Go in the environment `pipenv shell`
4. Make sure you have your awscli environment set up.
5. Create a BasicExecutionRole for your lambda to use.
6. Create the lambda function with `inv create` - supply the role you created. This creates the function and API.
7. Done. Get your API endpoint from API Gateway and invoke your lambda with all the HTML/CSS/Javascript you want. It'll stream the resulting pdf back to you.

If you make changes to the lambda code, run `inv deploy` to update it with everything inside the inner splat directory.
