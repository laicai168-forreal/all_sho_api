import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Duration } from 'aws-cdk-lib';
import { IBucket } from 'aws-cdk-lib/aws-s3';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { IVpc } from 'aws-cdk-lib/aws-ec2';
import { IDatabaseInstance } from 'aws-cdk-lib/aws-rds';
import { ITable } from 'aws-cdk-lib/aws-dynamodb';

export interface CrawlerConstructProps {
    bucket: IBucket;
    secret: ISecret;
    vpc: IVpc;
    carRDSInstance: IDatabaseInstance;
    logsTable: ITable;
    layer: lambda.ILayerVersion;
}

export class CrawlerConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: CrawlerConstructProps) {
        super(scope, id);

        const { bucket, secret, vpc, carRDSInstance, logsTable, layer } = props;

        const lambdaSG = new ec2.SecurityGroup(this, "CrawlerLambdaSG", {
            vpc,
            allowAllOutbound: true,
        });

        this.function = new lambda.Function(this, 'CrawlerLambda', {
            runtime: lambda.Runtime.PYTHON_3_12,
            code: lambda.Code.fromAsset('lambda/crawler'),
            handler: 'minigt_crawler.handler',
            environment: {
                BUCKET_NAME: bucket.bucketName,
                TARMAC_URL: 'https://www.tarmacworks.com/products/',
                MINIGT_URL: 'https://minigt.com/catalog/',
                INNO64_URL: 'https://www.inno-models.com/products/',
                HOTWHEELS_URL: 'https://hotwheels.fandom.com/',
                HOTWHEELS_164CUSTOM: 'https://164custom.com/',
                DB_SECRET_ARN: secret.secretArn,
                DB_NAME: 'carsdb',
                LOGS_TABLE_NAME: logsTable.tableArn,
            },
            timeout: Duration.minutes(10),
            // Use the CDK-bundled Python layer so dependencies are rebuilt for
            // the Lambda runtime instead of relying on a stale hand-zipped layer.
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
