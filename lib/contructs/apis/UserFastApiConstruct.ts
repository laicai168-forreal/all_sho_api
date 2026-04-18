// lib/constructs/apis/UserFastApiConstruct.ts

import { Construct } from "constructs";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import { Duration } from "aws-cdk-lib";
import * as secret from "aws-cdk-lib/aws-secretsmanager";
import * as s3 from "aws-cdk-lib/aws-s3";

interface UserFastApiConstructProps {
    httpApi: apigwv2.HttpApi;
    authorizer: apigwv2.IHttpRouteAuthorizer;
    vpc: ec2.Vpc;
    rds: rds.IDatabaseInstance;
    dbSecret: secret.ISecret;
    layer: lambda.LayerVersion;
    profileImageBucket: s3.IBucket;
}

export class UserFastApiConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: UserFastApiConstructProps) {
        super(scope, id);

        const { httpApi, authorizer, vpc, rds, dbSecret, layer, profileImageBucket } = props;

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
            },
        });

        // Attach layer
        this.function.addLayers(layer);

        // Allow DB access
        dbSecret.grantRead(this.function);
        rds.connections.allowDefaultPortFrom(this.function);
        profileImageBucket.grantReadWrite(this.function);

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
            methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
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
