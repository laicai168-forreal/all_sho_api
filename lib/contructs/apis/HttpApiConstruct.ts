import { Construct } from "constructs";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { JwtAuthorizer } from "./JwtAuthorizer";
import { CollectionRoutes } from "./CollectionRoutes";
import { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";

interface HttpApiConstructProps {
    addCollectionFn: LambdaFunction;
    deleteCollectionFn: LambdaFunction;
    likeCollectionFn: LambdaFunction;
    dislikeCollectionFn: LambdaFunction;
    userPoolId: string;
    appClientId: string;
}

export class HttpApiConstruct extends Construct {
    public readonly httpApi: apigwv2.HttpApi;

    constructor(scope: Construct, id: string, props: HttpApiConstructProps) {
        super(scope, id);

        const {
            addCollectionFn,
            deleteCollectionFn,
            likeCollectionFn,
            dislikeCollectionFn,
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

        // Collection routes
        new CollectionRoutes(this, "CollectionRoutes", {
            httpApi: this.httpApi,
            authorizer: authorizer.authorizer,
            addCollectionFn,
            deleteCollectionFn,
            likeCollectionFn,
            dislikeCollectionFn,
        });
    }
}