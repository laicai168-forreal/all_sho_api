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

## PostgreSQL Full-Text Search Setup for `cars` Table

### 1. Trigger Function

```sql
CREATE OR REPLACE FUNCTION update_search_vector() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector(
      'english',
      coalesce(NEW.id,'') || ' ' ||
      coalesce(NEW.original_id,'') || ' ' ||
      coalesce(NEW.scale,'') || ' ' ||
      coalesce(NEW.title,'') || ' ' ||
      coalesce(NEW.make,'') || ' ' ||
      coalesce(NEW.brand,'')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

```sql
CREATE TRIGGER trg_update_search_vector
BEFORE INSERT OR UPDATE ON cars
FOR EACH ROW
EXECUTE FUNCTION update_search_vector();
```

```sql
UPDATE cars
SET search_vector = to_tsvector(
    'english',
    coalesce(id,'') || ' ' ||
    coalesce(original_id,'') || ' ' ||
    coalesce(scale,'') || ' ' ||
    coalesce(title,'') || ' ' ||
    coalesce(make,'') || ' ' ||
    coalesce(brand,'')
);
```

For image lambda folder, in the lambda/image for dependencies do

```bash
docker run -it --rm -v "$PWD":/var/task amazonlinux:2023 bash
```

Install a dependency

```bash
dnf install -y gcc-c++ make python3
curl -fsSL https://rpm.nodesource.com/setup_18.x | bash -
dnf install -y nodejs
cd /var/task
npm install
```

```bash
./run_crawl.sh \
  "https://s3w40r0orl.execute-api.us-east-1.amazonaws.com/prod/run" \
  minigt \
  1 \
  catalogs.txt \
  20
```

### Structure

```sql
                        ┌───────────────────┐
                        │   Internet        │
                        └────────┬──────────┘
                                 │
                    ┌────────────┴────────────┐
                    │      Internet Gateway    │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │       Public Subnet      │
                    │       (CIDR /24)        │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │      NAT Gateway         │
                    └────────────┬────────────┘
                                 │
          ┌──────────────────────┴───────────────────────┐
          │                                              │
┌─────────┴─────────┐                          ┌─────────┴─────────┐
│ Private Lambda    │                          │ Private DB        │
│ Subnet (/24)      │                          │ Subnet (/24)      │
│ - Lambda Function │                          │ - RDS Instance    │
│ - Route via NAT   │                          │ - No Internet     │
└─────────┬─────────┘                          └─────────┬─────────┘
          │                                               │
          │                                               │
          │                                               │
          │                                               │
          │          ┌───────────────────────┐            │
          │          │ Secrets Manager       │◄───────────┘
          │          └───────────────────────┘
          │
          │
          ▼
┌───────────────────────┐
│ DynamoDB Tables        │
│ - Car Table            │
│ - User Collection      │
└───────────────────────┘
```
