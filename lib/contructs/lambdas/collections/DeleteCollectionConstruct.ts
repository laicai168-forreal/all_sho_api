import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import path from 'path';
import { IDatabaseInstance } from 'aws-cdk-lib/aws-rds';
import { IVpc } from 'aws-cdk-lib/aws-ec2';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';

export interface DeleteCollectionConstructProps {
    secret: ISecret;
    carRDSInstance: IDatabaseInstance;
    vpc: IVpc;
}

export class DeleteCollectionConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: DeleteCollectionConstructProps) {
        super(scope, id);

        const { secret, carRDSInstance, vpc } = props;

        const deps = new lambda.LayerVersion(this, 'UserCollectionDeleteDepsLayer', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda-layer/lambda_layer.zip')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'UserCollectionDelete dependencies layer',
        });

        this.function = new lambda.Function(this, "UserCollectionDelete", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "delete.handler",
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