import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';

import { ITable } from 'aws-cdk-lib/aws-dynamodb';
import path from 'path';

export interface DeleteCollectionConstructProps {
    table: ITable;
}

export class DeleteCollectionConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: DeleteCollectionConstructProps) {
        super(scope, id);

        const { table } = props;

        this.function = new lambda.Function(this, "UserCollectionDelete", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "delete.handler",
            code: lambda.Code.fromAsset("lambda/api/collection"),
            environment: {
                TABLE_NAME: table.tableName,
            },
        });

        table.grantWriteData(this.function);
    }
}