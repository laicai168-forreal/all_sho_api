import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as path from 'path';
import { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { IVpc } from 'aws-cdk-lib/aws-ec2';

interface CarApiProps {
    dynamoTable: dynamodb.ITable;
    userCollectionTable: dynamodb.ITable;
    secret: ISecret;
    vpc: IVpc;
}

export class CarApi extends Construct {
    public readonly api: apigateway.RestApi;

    constructor(scope: Construct, id: string, props: CarApiProps) {
        super(scope, id);

        const { dynamoTable, secret, userCollectionTable, vpc } = props;

        const crawlerDeps = new lambda.LayerVersion(this, 'CrawlerDepsLayer', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda-layer/lambda_layer.zip')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'Crawler dependencies layer',
        });

        const apiLambda = new lambda.Function(this, 'CarApiHandler', {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: 'car.handler',
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda/api/cars')),
            environment: {
                CAR_TABLE_NAME: dynamoTable.tableName,
                USER_COLLECTION_TABLE_NAME: userCollectionTable.tableName,
                DB_SECRET_ARN: secret.secretArn,
                DB_NAME: 'carsdb',
            },
            layers: [crawlerDeps],
            vpc
        });

        dynamoTable.grantReadData(apiLambda);
        secret.grantRead(apiLambda);
        userCollectionTable.grantReadData(apiLambda);

        this.api = new apigateway.RestApi(this, 'CarApi', {
            restApiName: 'Car Data Service',
            description: 'Provides access to car data from the crawler.',
            defaultCorsPreflightOptions: {
                allowOrigins: apigateway.Cors.ALL_ORIGINS,
                allowMethods: apigateway.Cors.ALL_METHODS,
            },
        });

        const cars = this.api.root.addResource('cars');
        cars.addMethod('GET', new apigateway.LambdaIntegration(apiLambda));
    }
}
