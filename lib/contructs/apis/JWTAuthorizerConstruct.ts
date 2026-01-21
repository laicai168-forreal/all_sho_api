import { Construct } from "constructs"
import * as apigw from "aws-cdk-lib/aws-apigateway";
import { Function } from "aws-cdk-lib/aws-lambda";

interface JWTAuthorizerConstructProps {
    jwtAuthLayeredFn: Function,
}

export class JWTAuthorizerConstruct extends Construct {
    public readonly authorizer: apigw.TokenAuthorizer;

    constructor(scope: Construct, id: string, props: JWTAuthorizerConstructProps) {
        super(scope, id);
        const { jwtAuthLayeredFn } = props;
        this.authorizer = new apigw.TokenAuthorizer(this, 'jwttokenAuth', {
            handler: jwtAuthLayeredFn,
            validationRegex: "^(Bearer )[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+?\.([a-zA-Z0-9\-_]+)$",
        });
    }
}