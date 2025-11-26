import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';

import { ITable } from 'aws-cdk-lib/aws-dynamodb';

export interface AddCollectionConstructProps {
    table: ITable;
}

export class AddCollectionConstruct extends Construct {
    public readonly function: lambda.Function;

    constructor(scope: Construct, id: string, props: AddCollectionConstructProps) {
        super(scope, id);

        const { table } = props;

        this.function = new lambda.Function(this, "UserCollectionAdd", {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "add.handler",
            code: lambda.Code.fromAsset("lambda/api/collection"),
            environment: {
                TABLE_NAME: table.tableName,
            },
        });

        table.grantReadWriteData(this.function);
    }
}