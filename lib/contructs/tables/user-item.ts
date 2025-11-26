import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { RemovalPolicy } from 'aws-cdk-lib';

export class UserItemDatabaseConstruct extends Construct {
    public readonly table: dynamodb.Table;

    constructor(scope: Construct, id: string) {
        super(scope, id);

        this.table = new dynamodb.Table(this, "UserItemTable", {
            partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
            sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            removalPolicy: RemovalPolicy.DESTROY,
        });

        // Add a GSI for querying by carId
        this.table.addGlobalSecondaryIndex({
            indexName: "GSI1",
            partitionKey: { name: "gsi1pk", type: dynamodb.AttributeType.STRING },
            sortKey: { name: "gsi1sk", type: dynamodb.AttributeType.STRING },
        });
    }
}