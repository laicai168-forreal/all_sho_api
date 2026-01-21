import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { RemovalPolicy } from 'aws-cdk-lib';

export class CarsDynamoConstruct extends Construct {
    public readonly table: dynamodb.Table;

    constructor(scope: Construct, id: string) {
        super(scope, id);

        this.table = new dynamodb.Table(this, 'DiecastCarsTable', {
            partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
            // sortKey: { name: 'brand', type: dynamodb.AttributeType.STRING },
            billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
            removalPolicy: RemovalPolicy.RETAIN,
        });

        // Example indexes for searching/sorting
        this.table.addGlobalSecondaryIndex({
            indexName: 'CarNameIndex',
            partitionKey: { name: 'carName', type: dynamodb.AttributeType.STRING },
        });
        this.table.addGlobalSecondaryIndex({
            indexName: 'ScaleIndex',
            partitionKey: { name: 'scale', type: dynamodb.AttributeType.STRING },
        });
    }
}