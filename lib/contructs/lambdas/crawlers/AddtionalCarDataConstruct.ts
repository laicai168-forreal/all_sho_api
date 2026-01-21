import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Duration } from 'aws-cdk-lib';
import { IBucket } from 'aws-cdk-lib/aws-s3';
import path from 'path';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { IVpc } from 'aws-cdk-lib/aws-ec2';
import { IDatabaseInstance } from 'aws-cdk-lib/aws-rds';
import { ITable } from 'aws-cdk-lib/aws-dynamodb';

export interface AddtionalCarDataPopulatorConstructProps {
    bucket: IBucket;
    secret: ISecret;
    vpc: IVpc;
    carRDSInstance: IDatabaseInstance;
    logsTable: ITable;
}

export class AddtionalCarDataPopulatorConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: AddtionalCarDataPopulatorConstructProps) {
        super(scope, id);

        const { bucket, secret, vpc, carRDSInstance, logsTable } = props;

        const populatorSG = new ec2.SecurityGroup(this, "AdditionalPopulatorSG", {
            vpc,
            description: "SG for Additional Car Data Populator Lambda",
            allowAllOutbound: true,
        });

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
                BUCKET_NAME: bucket.bucketName,
                DB_SECRET_ARN: secret.secretArn,
                DB_NAME: 'carsdb',
                LOGS_TABLE_NAME: logsTable.tableArn,
            },
            timeout: Duration.minutes(10),
            layers: [addtionalCarDataDeps],
            vpc,
            vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
            securityGroups: [populatorSG],
            allowPublicSubnet: false,
        });

        secret.grantRead(this.function);
        bucket.grantReadWrite(this.function);
        carRDSInstance.connections.allowDefaultPortFrom(this.function);
        logsTable.grantWriteData(this.function);
    }
}