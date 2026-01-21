import { Construct } from "constructs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as apigw from "aws-cdk-lib/aws-apigateway";
import path from "path";

export class CrawlerLoggingConstruct extends Construct {
    public readonly logsTable: dynamodb.Table;
    public readonly pollLambda: lambda.Function;

    constructor(scope: Construct, id: string) {
        super(scope, id);

        this.logsTable = new dynamodb.Table(this, "CrawlerLogsTable", {
            partitionKey: { name: "jobId", type: dynamodb.AttributeType.STRING },
            sortKey: { name: "ts", type: dynamodb.AttributeType.NUMBER },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            timeToLiveAttribute: "expireAt",
        });

        const helperLayer = new lambda.LayerVersion(this, 'HelperLayer', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../lambda-layer')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'Shared helper utilities for all Lambdas',
        });

        this.pollLambda = new lambda.Function(this, "PollCrawlerLogsLambda", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "poll.handler",
            code: lambda.Code.fromAsset("lambda/log"),
            environment: {
                LOG_TABLE: this.logsTable.tableName
            },
            layers: [helperLayer]
        });

        this.logsTable.grantReadData(this.pollLambda);

        const api = new apigw.RestApi(this, "CrawlerLogsApi", {
            restApiName: "Crawler Log",
            defaultCorsPreflightOptions: {
                allowOrigins: apigw.Cors.ALL_ORIGINS,
                allowMethods: apigw.Cors.ALL_METHODS,
            },
        });

        const logsResource = api.root.addResource("poll-crawler-logs");
        logsResource.addMethod("GET", new apigw.LambdaIntegration(this.pollLambda));
    }
}
