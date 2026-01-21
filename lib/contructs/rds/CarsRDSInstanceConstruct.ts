import { Construct } from "constructs";
import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import { IVpc } from "aws-cdk-lib/aws-ec2";

interface CarsRDSInstanceConstructProps {
    vpc: IVpc;
}

export class CarsRDSInstanceConstruct extends Construct {
    public readonly instance: rds.DatabaseInstance;

    constructor(scope: Construct, id: string, props: CarsRDSInstanceConstructProps) {
        super(scope, id);

        const { vpc } = props;

        const dbSG = new ec2.SecurityGroup(this, "CarsDBSG", {
            vpc,
            allowAllOutbound: true,
        });


        this.instance = new rds.DatabaseInstance(this, 'CarsPSQL', {
            engine: rds.DatabaseInstanceEngine.postgres({
                version: rds.PostgresEngineVersion.VER_14_12,
            }),
            vpc,
            instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
            allocatedStorage: 20,
            maxAllocatedStorage: 100,
            multiAz: false,
            credentials: rds.Credentials.fromGeneratedSecret('dbadmin'),
            databaseName: 'carsdb',
            storageEncrypted: true,
            backupRetention: cdk.Duration.days(1),
            deletionProtection: false,
            removalPolicy: cdk.RemovalPolicy.RETAIN,
            vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
            securityGroups: [dbSG],
            publiclyAccessible: false,
        });
    }

}
