# Welcome to your CDK TypeScript project

This is a project for CDK development with TypeScript.

The `cdk.json` file tells the CDK Toolkit how to execute your app.

## To update the lambda dependencies

``` bash
# Clean old layer
rm -rf lambda-layer/python lambda-layer/lambda_layer.zip
mkdir -p lambda-layer/python

# Install dependencies in correct arch
pip install --upgrade pip
pip install -r lambda-layer/requirements.txt -t lambda-layer/python

# Copy helpers
cp -r lambda-layer/helper lambda-layer/python/

# Zip it
cd lambda-layer
zip -r lambda_layer.zip python
cd ..
```

## Useful commands

* `npm run build`   compile typescript to js
* `npm run watch`   watch for changes and compile
* `npm run test`    perform the jest unit tests
* `npx cdk deploy`  deploy this stack to your default AWS account/region
* `npx cdk diff`    compare deployed stack with current state
* `npx cdk synth`   emits the synthesized CloudFormation template
