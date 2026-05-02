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

## Messaging Architecture Notes

The collector-to-collector messaging feature now uses a hybrid design:

- FastAPI HTTP endpoints for authenticated inbox, thread, send, read, and websocket ticket APIs
- a single DynamoDB table for message storage, inbox summaries, rate-limit counters, websocket connections, and one-time socket tickets
- an API Gateway WebSocket API for realtime delivery

### Current message flow

1. The frontend loads inbox and thread data through FastAPI.
2. The frontend requests a one-time websocket ticket from the authenticated HTTP API.
3. The websocket connect Lambda validates the ticket and stores live connection records in DynamoDB.
4. When a message is sent, the backend persists it to DynamoDB first.
5. The backend then performs best-effort websocket fanout to the recipient's active connections.
6. Inbox unread counts and thread read markers are also stored in DynamoDB.

### Single-table record groups

The messaging table uses `pk` and `sk` with several record shapes:

- `CONV#... / META`
  - conversation summary and request-lock state
- `CONV#... / MSG#...`
  - actual message rows
- `USER#... / CONV#...`
  - per-user inbox summaries and unread counts
- `USER#... / WS#...`
  - active websocket connection records
- `CONN#... / META`
  - reverse lookup for disconnect cleanup
- `TICKET#... / META`
  - one-time websocket ticket records
- `RATE#... / ...`
  - lightweight anti-spam counters

### Pre-production safeguards

Before production, the messaging service now includes:

- paged thread loading instead of fetching the full conversation at once
- best-effort websocket delivery so persistence does not fail when fanout fails
- websocket retry limits instead of endless reconnect loops on the client
- backend-enforced rate limits for message bursts and new intro requests
- message length limit of `500` characters

### Deferred work

Transaction-context messaging remains intentionally deferred for a later phase. The current system is designed so a later selling-post context can be layered on top of the existing direct-message flow instead of creating a separate message stack.

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
