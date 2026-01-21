import { Construct } from "constructs";
import * as apigwv2Auth from "aws-cdk-lib/aws-apigatewayv2-authorizers";

export interface JwtAuthorizerProps {
    userPoolId: string;
    appClientId: string;
}

export class JwtAuthorizer extends Construct {
    public readonly authorizer: apigwv2Auth.HttpJwtAuthorizer;

    constructor(scope: Construct, id: string, props: JwtAuthorizerProps) {
        super(scope, id);

        const { userPoolId, appClientId } = props;

        this.authorizer = new apigwv2Auth.HttpJwtAuthorizer(
            "CognitoJwtAuthorizer",
            `https://cognito-idp.us-east-1.amazonaws.com/${userPoolId}`,
            {
                jwtAudience: [appClientId],
            }
        );
    }
}
