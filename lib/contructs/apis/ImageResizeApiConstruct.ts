import { Construct } from "constructs"
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import { Function } from "aws-cdk-lib/aws-lambda";

interface ImageResizeApiConstructProps {
    imageResizeLambda: Function
}

export class ImageResizeApiConstruct extends Construct {
    public readonly api: apigateway.RestApi;

    constructor(scope: Construct, id: string, props: ImageResizeApiConstructProps) {
        super(scope, id);

        const { imageResizeLambda } = props;
        this.api = new apigateway.LambdaRestApi(this, "ImageResizeApi", {
            handler: imageResizeLambda,
            proxy: true,
            defaultMethodOptions: {
                apiKeyRequired: false
            },
            binaryMediaTypes: ['image/jpeg', 'image/png'],
        });
    }
}