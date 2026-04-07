import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import path from 'path';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { IDatabaseInstance } from 'aws-cdk-lib/aws-rds';
import { IVpc } from 'aws-cdk-lib/aws-ec2';

export interface GetCollectionConstructProps {
    secret: ISecret;
    carRDSInstance: IDatabaseInstance;
    vpc: IVpc;
}

export class GetCollectionConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: GetCollectionConstructProps) {
        super(scope, id);

        const { secret, carRDSInstance, vpc } = props;
        const deps = new lambda.LayerVersion(this, 'HelperLayer', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda-layer')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'Shared helper utilities for all Lambdas',
        });

        this.function = new lambda.Function(this, "UserCollectionGet", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "get.handler",
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