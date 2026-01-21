import { Construct } from "constructs";
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as cdk from 'aws-cdk-lib';
import { IBucket } from "aws-cdk-lib/aws-s3";
import path from "path";

interface ImagesResizingLambdaConstructProps {
    imageBucket: IBucket,
    oldBucket: IBucket,
}

export class ImagesResizingLambdaConstruct extends Construct {
    public readonly function: lambda.Function;
    public readonly functionUrl: lambda.FunctionUrl;

    constructor(scope: Construct, id: string, props: ImagesResizingLambdaConstructProps) {
        super(scope, id);

        const { imageBucket, oldBucket } = props;

        const pillowLayer = new lambda.LayerVersion(this, 'PillowLayer', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda-layer/lambda_layer.zip')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'Pillow layer for image processing',
        });

        this.function = new lambda.Function(this, "ImageResizeLambda", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "index.lambda_handler",
            code: lambda.Code.fromAsset("lambda/image_resize"),
            timeout: cdk.Duration.seconds(10),
            memorySize: 512,
            environment: {
                IMAGE_BUCKET: imageBucket.bucketName,
                OLD_BUCKET: oldBucket.bucketName,
            },
            layers: [pillowLayer],
        });

        imageBucket.grantRead(this.function);
        oldBucket.grantRead(this.function);

        this.functionUrl = this.function.addFunctionUrl({
            authType: lambda.FunctionUrlAuthType.NONE,
        });
    }
}