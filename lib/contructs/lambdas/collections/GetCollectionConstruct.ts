import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';

import { ITable } from 'aws-cdk-lib/aws-dynamodb';
import path from 'path';

export interface GetCollectionConstructProps {
    table: ITable;
}

export class GetCollectionConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: GetCollectionConstructProps) {
        super(scope, id);

        const { table } = props;
        const helperLayer = new lambda.LayerVersion(this, 'HelperLayer', {
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../../lambda-layer')),
            compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
            description: 'Shared helper utilities for all Lambdas',
        });

        this.function = new lambda.Function(this, "UserCollectionGet", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "get.handler",
            code: lambda.Code.fromAsset("lambda/api/collection"),
            environment: {
                TABLE_NAME: table.tableName,
            },
            layers: [helperLayer],
        });

        table.grantReadData(this.function);
    }
}