import { RemovalPolicy } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';

export class ProfileImageBucketConstruct extends Construct {
    public readonly bucket: s3.Bucket;

    constructor(scope: Construct, id: string) {
        super(scope, id);

        this.bucket = new s3.Bucket(this, 'ProfileImagesBucket', {
            versioned: true,
            encryption: s3.BucketEncryption.S3_MANAGED,
            removalPolicy: RemovalPolicy.RETAIN,
            blockPublicAccess: s3.BlockPublicAccess.BLOCK_ACLS_ONLY,
            objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            cors: [
                {
                    allowedOrigins: ['*'],
                    allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.PUT, s3.HttpMethods.HEAD],
                    allowedHeaders: ['*'],
                },
            ],
        });

        this.bucket.addToResourcePolicy(new iam.PolicyStatement({
            sid: 'AllowPublicReadProfileImages',
            actions: ['s3:GetObject'],
            resources: [`${this.bucket.bucketArn}/*`],
            principals: [new iam.AnyPrincipal()],
        }));
    }
}
