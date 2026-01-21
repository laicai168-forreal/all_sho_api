import { Construct } from 'constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam'
import { RemovalPolicy } from 'aws-cdk-lib';
import { AwsCustomResource } from 'aws-cdk-lib/custom-resources';

export class CrawlerBucketConstruct extends Construct {
    public readonly bucket: s3.Bucket;
    public readonly oldBucket: s3.IBucket;

    private readonly oldBucketArn: string;
    private readonly oldBucketName: string;

    constructor(scope: Construct, id: string) {
        super(scope, id);

        this.oldBucketArn = "arn:aws:s3:::laicaiapistack-crawlerbucketdiecastdatabucketaaab0-sthyni3cuj9w";
        this.oldBucketName = this.oldBucketArn.split(':::')[1];

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


        this.oldBucket = s3.Bucket.fromBucketArn(
            this,
            'OldDiecastDataBucket',
            this.oldBucketArn
        );

        // this.oldBucket.addToResourcePolicy(
        //     new iam.PolicyStatement({
        //         sid: 'AllowPublicReadOld',
        //         actions: ['s3:GetObject'],
        //         resources: [`${this.oldBucketArn}/*`],
        //         principals: [new iam.AnyPrincipal()],
        //     })
        // );

        new s3.CfnBucketPolicy(this, 'OldBucketPolicy', {
            bucket: this.oldBucket.bucketName,
            policyDocument: {
                Version: '2012-10-17',
                Statement: [{
                    Sid: 'AllowPublicReadOld',
                    Effect: 'Allow',
                    Action: 's3:GetObject',
                    Resource: `${this.oldBucketArn}/*`,
                    Principal: '*'
                }]
            }
        });


    }
}