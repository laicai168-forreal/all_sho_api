import boto3
import os
from boto3.dynamodb.conditions import Key
import json
from helper.utils import DecimalEncoder

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["LOG_TABLE"])


def handler(event, context):
    job_id = event["queryStringParameters"]["jobId"]
    last_ts_str = event["queryStringParameters"].get("lastTs", "0")
    last_ts = int(last_ts_str)

    resp = table.query(
        KeyConditionExpression=Key("jobId").eq(job_id) & Key("ts").gt(last_ts),
        ScanIndexForward=True,  # ascending order (oldest → newest)
    )

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(
            {"logs": resp["Items"], "hasMore": "LastEvaluatedKey" in resp},
            cls=DecimalEncoder,
        ),
    }
