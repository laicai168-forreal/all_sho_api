import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Duration } from 'aws-cdk-lib';
import { IBucket } from 'aws-cdk-lib/aws-s3';
import { ITable } from 'aws-cdk-lib/aws-dynamodb';
import path from 'path';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { IVpc } from 'aws-cdk-lib/aws-ec2';

export interface AddtionalCarDataPopulatorConstructProps {
    bucket: IBucket;
    table: ITable;
    secret: ISecret;
    vpc: IVpc;
}

export class AddtionalCarDataPopulatorConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: AddtionalCarDataPopulatorConstructProps) {
        super(scope, id);

        const { bucket, table, secret, vpc } = props;

        const addtionalCarDataDeps = new lambda.LayerVersion(this, 'AddtionalCarDataDeps', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda-layer/lambda_layer.zip')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'Addtional car data populator dependencies layer',
        });

        this.function = new lambda.Function(this, 'AddtionalCarDataPopulatorLambda', {
            runtime: lambda.Runtime.PYTHON_3_12,
            code: lambda.Code.fromAsset('lambda/crawler'),
            handler: 'addtional_car_data_populator.handler',
            environment: {
                TABLE_NAME: table.tableName,
                BUCKET_NAME: bucket.bucketName,
                DB_SECRET_ARN: secret.secretArn,
                DB_NAME: 'carsdb',
            },
            timeout: Duration.minutes(10),
            layers: [addtionalCarDataDeps],
            vpc,
        });

        secret.grantRead(this.function);
        table.grantReadWriteData(this.function);
        bucket.grantReadWrite(this.function);
    }
}