import { Construct } from "constructs"
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import { Function } from "aws-cdk-lib/aws-lambda";

interface AdditionalDataHelperApiConstructProps {
    addtionalDataFunction: Function,
}

export class AdditionalDataHelperApiConstruct extends Construct {
    public readonly api: apigateway.RestApi;

    constructor(scope: Construct, id: string, props: AdditionalDataHelperApiConstructProps) {
        super(scope, id);

        const { addtionalDataFunction } = props;
        this.api = new apigateway.RestApi(this, "AddtionalDataHelperApi", {
            restApiName: "Car Data Addtiontional Data Api Helpers",
            defaultCorsPreflightOptions: {
                allowOrigins: apigateway.Cors.ALL_ORIGINS,
                allowMethods: apigateway.Cors.ALL_METHODS,
            },
        });

        const addData = this.api.root.addResource('add');

        addData.addMethod("POST", new apigateway.LambdaIntegration(addtionalDataFunction));
    }
}