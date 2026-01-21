import { Construct } from 'constructs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { RestApi } from 'aws-cdk-lib/aws-apigateway';

export interface JWTAuthConstructProps {
    authApiGateway: RestApi;
    region: string;
    account: string;
}

export class JWTAuthConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: JWTAuthConstructProps) {
        super(scope, id);

        const { authApiGateway, region, account } = props;

        this.function = new lambda.Function(this, "jwtAuthLayeredFn", {
            timeout: cdk.Duration.seconds(40),
            runtime: lambda.Runtime.NODEJS_18_X,
            handler: 'index.handler',
            code: lambda.Code.fromAsset(path.join(__dirname, "../../../../lambda/jwt-auth")),
            environment: {
                API_ID: authApiGateway.restApiId,
                API_REGION: region,
                ACCOUNT_ID: account,
                COGNITO_USER_POOL_ID: 'us-east-1_Fin5RlUdn',
                COGNITO_APP_CLIENT_ID: '6ja446jgvp1839q7tr624d4tc8',
            },
            allowPublicSubnet: true,
            vpc: undefined,
        });
    }
}