import { Duration } from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { WebSocketLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";

interface UserMessagingRealtimeConstructProps {
    userMessagingTable: dynamodb.ITable;
}

export class UserMessagingRealtimeConstruct extends Construct {
    public readonly webSocketApi: apigwv2.WebSocketApi;
    public readonly stage: apigwv2.WebSocketStage;

    constructor(scope: Construct, id: string, props: UserMessagingRealtimeConstructProps) {
        super(scope, id);

        const { userMessagingTable } = props;

        const connectFn = new lambda.Function(this, "MessagingWsConnectFn", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "connect.handler",
            code: lambda.Code.fromAsset("lambda/websocket"),
            memorySize: 256,
            timeout: Duration.seconds(10),
            environment: {
                USER_MESSAGING_TABLE: userMessagingTable.tableName,
            },
        });

        const disconnectFn = new lambda.Function(this, "MessagingWsDisconnectFn", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "disconnect.handler",
            code: lambda.Code.fromAsset("lambda/websocket"),
            memorySize: 256,
            timeout: Duration.seconds(10),
            environment: {
                USER_MESSAGING_TABLE: userMessagingTable.tableName,
            },
        });

        const defaultFn = new lambda.Function(this, "MessagingWsDefaultFn", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "default.handler",
            code: lambda.Code.fromAsset("lambda/websocket"),
            memorySize: 256,
            timeout: Duration.seconds(10),
        });

        userMessagingTable.grantReadWriteData(connectFn);
        userMessagingTable.grantReadWriteData(disconnectFn);

        this.webSocketApi = new apigwv2.WebSocketApi(this, "MessagingWebSocketApi", {
            connectRouteOptions: {
                integration: new WebSocketLambdaIntegration("MessagingConnectIntegration", connectFn),
            },
            disconnectRouteOptions: {
                integration: new WebSocketLambdaIntegration("MessagingDisconnectIntegration", disconnectFn),
            },
            defaultRouteOptions: {
                integration: new WebSocketLambdaIntegration("MessagingDefaultIntegration", defaultFn),
            },
        });

        this.stage = new apigwv2.WebSocketStage(this, "MessagingWebSocketStage", {
            webSocketApi: this.webSocketApi,
            stageName: "live",
            autoDeploy: true,
        });
    }
}
