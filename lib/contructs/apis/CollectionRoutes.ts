import { Construct } from "constructs";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as apigwv2Integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import { Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { HttpJwtAuthorizer } from "aws-cdk-lib/aws-apigatewayv2-authorizers";

interface CollectionRoutesProps {
    httpApi: apigwv2.HttpApi;
    authorizer: HttpJwtAuthorizer;
    addCollectionFn: LambdaFunction;
    deleteCollectionFn: LambdaFunction;
    likeCollectionFn: LambdaFunction;
    dislikeCollectionFn: LambdaFunction;
}

export class CollectionRoutes extends Construct {
    constructor(scope: Construct, id: string, props: CollectionRoutesProps) {
        super(scope, id);

        const { httpApi, authorizer, addCollectionFn, deleteCollectionFn, likeCollectionFn, dislikeCollectionFn } = props;

        const routes = [
            { path: "/collections", method: apigwv2.HttpMethod.POST, fn: addCollectionFn },
            { path: "/collections", method: apigwv2.HttpMethod.DELETE, fn: deleteCollectionFn },
            { path: "/likes", method: apigwv2.HttpMethod.POST, fn: likeCollectionFn },
            { path: "/likes", method: apigwv2.HttpMethod.DELETE, fn: dislikeCollectionFn },
        ];

        routes.forEach(({ path, method, fn }) => {
            httpApi.addRoutes({
                path,
                methods: [method],
                integration: new apigwv2Integrations.HttpLambdaIntegration(`${fn.node.id}Integration`, fn),
                authorizer,
            });
        });
    }
}
