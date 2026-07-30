import { Construct } from "constructs";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { JwtAuthorizer } from "./JwtAuthorizer";

interface HttpApiConstructProps {
    userPoolId: string;
    appClientId: string;
}

export class HttpApiConstruct extends Construct {
    public readonly httpApi: apigwv2.HttpApi;
    public readonly authorizer: apigwv2.IHttpRouteAuthorizer;

    constructor(scope: Construct, id: string, props: HttpApiConstructProps) {
        super(scope, id);

        const {
            userPoolId,
            appClientId,
        } = props;

        // HTTP API
        this.httpApi = new apigwv2.HttpApi(this, "UserCollectionsHttpApi", {
            apiName: "UserCollectionsAPI",
            corsPreflight: {
                allowOrigins: ["*"],
                allowHeaders: ["Authorization", "Content-Type"],
                allowMethods: [
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.DELETE,
                ],
            },
        });

        // JWT Authorizer
        const authorizer = new JwtAuthorizer(this, "JwtAuthorizer", {
            userPoolId,
            appClientId,
        });

        this.authorizer = authorizer.authorizer;
    }
}
