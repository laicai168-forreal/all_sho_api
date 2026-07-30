// lib/constructs/apis/UserFastApiConstruct.ts

import { Construct } from "constructs";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import { Duration, Stack } from "aws-cdk-lib";
import * as secret from "aws-cdk-lib/aws-secretsmanager";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";

interface UserFastApiConstructProps {
    httpApi: apigwv2.HttpApi;
    authorizer: apigwv2.IHttpRouteAuthorizer;
    vpc: ec2.Vpc;
    rds: rds.IDatabaseInstance;
    dbSecret: secret.ISecret;
    layer: lambda.LayerVersion;
    profileImageBucket: s3.IBucket;
    showroomImageBucket: s3.IBucket;
    carImageBucket: s3.IBucket;
    userMessagingTable: dynamodb.ITable;
    messagingWebSocketUrl: string;
    messagingWebSocketCallbackUrl: string;
}

export class UserFastApiConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: UserFastApiConstructProps) {
        super(scope, id);

        const {
            httpApi,
            authorizer,
            vpc,
            rds,
            dbSecret,
            layer,
            profileImageBucket,
            showroomImageBucket,
            carImageBucket,
            userMessagingTable,
            messagingWebSocketUrl,
            messagingWebSocketCallbackUrl,
        } = props;

        // Lambda
        this.function = new lambda.Function(this, "UserFastApiFn", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "app.handler.handler",
            code: lambda.Code.fromAsset("backend"),
            memorySize: 512,
            timeout: Duration.seconds(30),
            vpc,
            environment: {
                DB_SECRET_ARN: dbSecret.secretArn,
                DB_NAME: "carsdb",
                PROFILE_IMAGE_BUCKET: profileImageBucket.bucketName,
                SHOWROOM_IMAGE_BUCKET: showroomImageBucket.bucketName,
                CAR_IMAGE_BUCKET: carImageBucket.bucketName,
                USER_MESSAGING_TABLE: userMessagingTable.tableName,
                MESSAGING_WS_URL: messagingWebSocketUrl,
                MESSAGING_WS_CALLBACK_URL: messagingWebSocketCallbackUrl,
                BRAVE_SEARCH_API_KEY: process.env.BRAVE_SEARCH_API_KEY || "",
            },
        });

        // Attach layer
        this.function.addLayers(layer);

        // Allow DB access
        dbSecret.grantRead(this.function);
        rds.connections.allowDefaultPortFrom(this.function);
        profileImageBucket.grantReadWrite(this.function);
        showroomImageBucket.grantReadWrite(this.function);
        carImageBucket.grantReadWrite(this.function);
        userMessagingTable.grantReadWriteData(this.function);
        const stack = Stack.of(this);
        this.function.addToRolePolicy(new iam.PolicyStatement({
            actions: ["execute-api:ManageConnections"],
            resources: [
                `arn:aws:execute-api:${stack.region}:${stack.account}:*/*/@connections/*`,
            ],
        }));

        const integration = new HttpLambdaIntegration(
            "UserFastApiIntegration",
            this.function
        );

        // Explicit root route for POST /users
        httpApi.addRoutes({
            path: "/users",
            methods: [apigwv2.HttpMethod.POST],
            integration,
            authorizer,
        });

        // Proxy route for /users/me and future nested endpoints
        httpApi.addRoutes({
            path: "/users/{proxy+}",
            methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST, apigwv2.HttpMethod.DELETE],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/profiles/{user_id}",
            methods: [apigwv2.HttpMethod.GET],
            integration,
        });

        httpApi.addRoutes({
            path: "/profiles/{user_id}/{proxy+}",
            methods: [apigwv2.HttpMethod.GET],
            integration,
        });

        httpApi.addRoutes({
            path: "/showroom",
            methods: [apigwv2.HttpMethod.GET],
            integration,
        });

        httpApi.addRoutes({
            path: "/showroom",
            methods: [apigwv2.HttpMethod.POST],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/showroom/feed/{mode}",
            methods: [apigwv2.HttpMethod.GET],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/showroom/{proxy+}",
            methods: [apigwv2.HttpMethod.GET],
            integration,
        });

        httpApi.addRoutes({
            path: "/showroom/{proxy+}",
            methods: [apigwv2.HttpMethod.POST],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/showroom/{proxy+}",
            methods: [apigwv2.HttpMethod.PUT],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/showroom/{proxy+}",
            methods: [apigwv2.HttpMethod.DELETE],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/admin/{proxy+}",
            methods: [
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.POST,
                apigwv2.HttpMethod.DELETE,
            ],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/car-change-requests",
            methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/cars",
            methods: [apigwv2.HttpMethod.GET],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/brands",
            methods: [apigwv2.HttpMethod.GET],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/collections",
            methods: [
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.POST,
                apigwv2.HttpMethod.DELETE,
            ],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/likes",
            methods: [
                apigwv2.HttpMethod.GET,
                apigwv2.HttpMethod.POST,
                apigwv2.HttpMethod.DELETE,
            ],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/car-change-requests/{proxy+}",
            methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration,
            authorizer,
        });

        httpApi.addRoutes({
            path: "/admin/car-change-requests/{proxy+}",
            methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
            integration,
            authorizer,
        });
    }
}
