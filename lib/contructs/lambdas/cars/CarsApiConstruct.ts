import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as path from 'path';
import { IVpc } from 'aws-cdk-lib/aws-ec2';
import { DatabaseInstance } from 'aws-cdk-lib/aws-rds';
import { Duration } from 'aws-cdk-lib';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';

interface CarApiProps {
    userCollectionTable: dynamodb.ITable;
    likeCollectionTable: dynamodb.ITable;
    secret: ISecret;
    vpc: IVpc;
    rds: DatabaseInstance;
}

export class CarApi extends Construct {
    public readonly api: apigateway.RestApi;
    public readonly function: lambda.Function;

    constructor(
        scope: Construct,
        id: string,
        {
            userCollectionTable,
            likeCollectionTable,
            secret,
            vpc,
            rds
        }: CarApiProps) {
        super(scope, id);

        const crawlerDeps = new lambda.LayerVersion(this, 'CrawlerDepsLayer', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda-layer/lambda_layer.zip')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'Crawler dependencies layer',
        });

        this.function = new lambda.Function(this, 'CarApiHandler', {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: 'car.handler',
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda/api/cars')),
            environment: {
                USER_COLLECTION_TABLE_NAME: userCollectionTable.tableName,
                LIKE_COLLECTION_TABLE_NAME: likeCollectionTable.tableName,
                DB_SECRET_ARN: secret.secretArn,
                DB_NAME: 'carsdb',
            },
            layers: [crawlerDeps],
            vpc,
            vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
            allowPublicSubnet: false,
            timeout: Duration.seconds(15),
        });

        userCollectionTable.grantReadData(this.function);
        likeCollectionTable.grantReadData(this.function);
        rds.connections.allowDefaultPortFrom(this.function);
        secret.grantRead(this.function);

        this.api = new apigateway.RestApi(this, 'CarApi', {
            restApiName: 'Car Data Service',
            description: 'Provides access to car data from the crawler.',
            defaultCorsPreflightOptions: {
                allowOrigins: apigateway.Cors.ALL_ORIGINS,
                allowMethods: apigateway.Cors.ALL_METHODS,
            },
        });

        const cars = this.api.root.addResource('cars');
        cars.addMethod('GET', new apigateway.LambdaIntegration(this.function));
    }
}
