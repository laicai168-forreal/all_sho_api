import { Construct } from "constructs"
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import { Function } from "aws-cdk-lib/aws-lambda";

interface UserCollectionApiConstructProps {
    addCollectionFunction: Function,
    getCollectionFunction: Function,
    deleteCollectionFunction: Function,
    likeCollectionFunction: Function,
    dislikeCollectionFunction: Function,
    // authorizer: apigateway.TokenAuthorizer;
}

export class UserCollectionApiConstruct extends Construct {
    public readonly api: apigateway.RestApi;

    constructor(
        scope: Construct,
        id: string,
        {
            addCollectionFunction,
            getCollectionFunction,
            deleteCollectionFunction,
            likeCollectionFunction,
            dislikeCollectionFunction,
            // authorizer
        }: UserCollectionApiConstructProps) {

        super(scope, id);

        this.api = new apigateway.RestApi(this, "CollectionsApi", {
            restApiName: "User Collections Service",
            defaultCorsPreflightOptions: {
                allowOrigins: apigateway.Cors.ALL_ORIGINS,
                allowMethods: apigateway.Cors.ALL_METHODS,
                allowHeaders: [
                    "Content-Type",
                    "Authorization",
                    "X-Amz-Date",
                    "X-Api-Key",
                    "X-Amz-Security-Token",
                ],
            },
        });

        const collections = this.api.root.addResource("collections");
        const likes = this.api.root.addResource("likes");

        this.api.addGatewayResponse("Default4xx", {
            type: apigateway.ResponseType.DEFAULT_4XX,
            responseHeaders: {
                "Access-Control-Allow-Origin": "'*'",
                "Access-Control-Allow-Headers": "'*'",
            },
        });

        this.api.addGatewayResponse("Default5xx", {
            type: apigateway.ResponseType.DEFAULT_5XX,
            responseHeaders: {
                "Access-Control-Allow-Origin": "'*'",
                "Access-Control-Allow-Headers": "'*'",
            },
        });

        collections.addMethod(
            "POST",
            new apigateway.LambdaIntegration(addCollectionFunction),
            // {
            //     authorizer
            // }
        );
        collections.addMethod(
            "GET", 
            new apigateway.LambdaIntegration(getCollectionFunction),
            // {
            //     authorizer
            // }
        );
        collections.addMethod(
            "DELETE", 
            new apigateway.LambdaIntegration(deleteCollectionFunction),
            // {
            //     authorizer
            // }
        );
        likes.addMethod(
            "POST", 
            new apigateway.LambdaIntegration(likeCollectionFunction),
            // {
            //     authorizer
            // }
        );
        likes.addMethod(
            "DELETE", 
            new apigateway.LambdaIntegration(dislikeCollectionFunction),
            // {
            //     authorizer
            // }
        );
    }
}