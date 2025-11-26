import { Construct } from 'constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam'
import { RemovalPolicy } from 'aws-cdk-lib';

export class CrawlerBucketConstruct extends Construct {
    public readonly bucket: s3.Bucket;

    constructor(scope: Construct, id: string) {
        super(scope, id);

        this.bucket = new s3.Bucket(this, 'DiecastDataBucket', {
            versioned: true,
            encryption: s3.BucketEncryption.S3_MANAGED,
            removalPolicy: RemovalPolicy.RETAIN,
            blockPublicAccess: s3.BlockPublicAccess.BLOCK_ACLS_ONLY,
            objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            cors: [
                {
                    allowedOrigins: ['*'],
                    allowedMethods: [s3.HttpMethods.GET],
                },
            ],
        });

        this.bucket.addToResourcePolicy(new iam.PolicyStatement({
            sid: 'AllowPublicRead',
            actions: ["s3:GetObject"],
            resources: [`${this.bucket.bucketArn}/*`],
            principals: [new iam.AnyPrincipal()],
        }));
    }
}