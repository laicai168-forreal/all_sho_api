import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Duration } from 'aws-cdk-lib';
import { IBucket } from 'aws-cdk-lib/aws-s3';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { IVpc } from 'aws-cdk-lib/aws-ec2';
import { IDatabaseInstance } from 'aws-cdk-lib/aws-rds';
import { ITable } from 'aws-cdk-lib/aws-dynamodb';

export interface PopRaceCrawlerConstructProps {
    bucket: IBucket;
    secret: ISecret;
    vpc: IVpc;
    carRDSInstance: IDatabaseInstance;
    logsTable: ITable;
    layer: lambda.ILayerVersion;
}

export class PopRaceCrawlerConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: PopRaceCrawlerConstructProps) {
        super(scope, id);

        const { bucket, secret, vpc, carRDSInstance, logsTable, layer } = props;

        const lambdaSG = new ec2.SecurityGroup(this, "PopRaceCrawlerLambdaSG", {
            vpc,
            allowAllOutbound: true,
        });

        this.function = new lambda.Function(this, 'CrawlerPopRaceLambda', {
            runtime: lambda.Runtime.PYTHON_3_12,
            code: lambda.Code.fromAsset('lambda/crawler'),
            handler: 'pop_race_crawler.handler',
            environment: {
                BUCKET_NAME: bucket.bucketName,
                DB_SECRET_ARN: secret.secretArn,
                DB_NAME: 'carsdb',
                LOGS_TABLE_NAME: logsTable.tableArn,
            },
            timeout: Duration.minutes(10),
            layers: [layer],
            vpc,
            vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
            securityGroups: [lambdaSG],
            allowPublicSubnet: false,
        });

        secret.grantRead(this.function);
        bucket.grantReadWrite(this.function);
        carRDSInstance.connections.allowDefaultPortFrom(this.function);
        logsTable.grantWriteData(this.function);
    }
}
