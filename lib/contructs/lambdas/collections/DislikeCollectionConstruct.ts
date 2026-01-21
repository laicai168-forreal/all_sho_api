import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { IDatabaseInstance } from 'aws-cdk-lib/aws-rds';
import { IVpc } from 'aws-cdk-lib/aws-ec2';
import path from 'path';

export interface DislikeCollectionConstructProps {
    secret: ISecret;
    carRDSInstance: IDatabaseInstance;
    vpc: IVpc;
}

export class DislikeCollectionConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: DislikeCollectionConstructProps) {
        super(scope, id);

        const { secret, carRDSInstance, vpc } = props;

        const deps = new lambda.LayerVersion(this, 'UserCollectionDislikeDepsLayer', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda-layer/lambda_layer.zip')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'UserCollectionDislike dependencies layer',
        });

        this.function = new lambda.Function(this, "UserCollectionDislike", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "dislike.handler",
            code: lambda.Code.fromAsset("lambda/api/collection"),
            environment: {
                SECRET_ARN: secret.secretArn,
                DB_NAME: 'carsdb',
            },
            layers: [deps],
            vpc
        });

        secret.grantRead(this.function);
        carRDSInstance.connections.allowDefaultPortFrom(this.function);
    }
}