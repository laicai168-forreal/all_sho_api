import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Duration } from 'aws-cdk-lib';
import { IBucket } from 'aws-cdk-lib/aws-s3';
import { ITable } from 'aws-cdk-lib/aws-dynamodb';
import path from 'path';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { IVpc } from 'aws-cdk-lib/aws-ec2';

export interface CrawlerConstructProps {
    bucket: IBucket;
    table: ITable;
    secret: ISecret;
    vpc: IVpc;
}

export class CrawlerConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: CrawlerConstructProps) {
        super(scope, id);

        const { bucket, table, secret, vpc } = props;

        const crawlerDeps = new lambda.LayerVersion(this, 'CrawlerDepsLayer', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda-layer/lambda_layer.zip')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'Crawler dependencies layer',
        });

        this.function = new lambda.Function(this, 'CrawlerLambda', {
            runtime: lambda.Runtime.PYTHON_3_12,
            code: lambda.Code.fromAsset('lambda/crawler'),
            handler: 'minigt_crawler.handler',
            environment: {
                TABLE_NAME: table.tableName,
                BUCKET_NAME: bucket.bucketName,
                TARMAC_URL: 'https://www.tarmacworks.com/products/',
                MINIGT_URL: 'https://minigt.com/catalog/',
                INNO64_URL: 'https://www.inno-models.com/products/',
                HOTWHEELS_URL: 'https://hotwheels.fandom.com/',
                HOTWHEELS_164CUSTOM: 'https://164custom.com/',
                DB_SECRET_ARN: secret.secretArn,
                DB_NAME: 'carsdb',
            },
            timeout: Duration.minutes(10),
            layers: [crawlerDeps],
            vpc,
        });

        secret.grantRead(this.function);
        table.grantReadWriteData(this.function);
        bucket.grantReadWrite(this.function);
    }
}