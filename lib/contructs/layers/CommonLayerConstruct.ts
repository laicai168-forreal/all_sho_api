// lib/constructs/layers/CommonLayerConstruct.ts

import { Construct } from "constructs";
import * as lambda from "aws-cdk-lib/aws-lambda";

export class CommonLayerConstruct extends Construct {
    public readonly layer: lambda.LayerVersion;

    constructor(scope: Construct, id: string) {
        super(scope, id);

        this.layer = new lambda.LayerVersion(this, "CommonDepsLayer", {
            code: lambda.Code.fromAsset("lambda-layer", {
                bundling: {
                    image: lambda.Runtime.PYTHON_3_12.bundlingImage,
                    command: [
                        "bash", "-c",
                        [
                            "pip install -r requirements.txt -t /asset-output/python",
                            "cp -r python/* /asset-output/python/"
                        ].join(" && ")
                    ],
                },
            }),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
        });
    }
}