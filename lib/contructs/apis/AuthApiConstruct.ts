import { Construct } from "constructs"
import * as cdk from 'aws-cdk-lib';
import * as apigw from "aws-cdk-lib/aws-apigateway";
import * as log from "aws-cdk-lib/aws-logs";

export class AuthApiConstruct extends Construct {
    public readonly api: apigw.RestApi;

    constructor(scope: Construct, id: string) {
        super(scope, id);

        const authLogger = new log.LogGroup(this, 'api-gateway-logger', {
            retention: log.RetentionDays.ONE_WEEK,
            removalPolicy: cdk.RemovalPolicy.DESTROY,
        });

        this.api = new apigw.RestApi(this, 'AuthApi', {
            deployOptions: {
                loggingLevel: apigw.MethodLoggingLevel.INFO,
                accessLogDestination: new apigw.LogGroupLogDestination(authLogger),
                dataTraceEnabled: true,
                accessLogFormat: apigw.AccessLogFormat.jsonWithStandardFields(),
            },
        });

        this.api.root.addMethod('ANY');
    }
}