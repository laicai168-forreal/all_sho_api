import * as cdk from 'aws-cdk-lib';
import { Construct } from "constructs";
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';

interface Props {
    imageResizeFunctionUrl: string;
}

export class ImageResizeCfnConstruct extends Construct {
    public readonly cloudFront: cloudfront.Distribution;

    constructor(scope: Construct, id: string, props: Props) {
        super(scope, id);

        const { imageResizeFunctionUrl } = props;

        const origin = new origins.HttpOrigin(cdk.Fn.parseDomainName(imageResizeFunctionUrl), {
            protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY
        });

        const imageCachePolicy = new cloudfront.CachePolicy(this, "ImageResizeCachePolicy", {
            queryStringBehavior: cloudfront.CacheQueryStringBehavior.allowList(
                "width", "height", "quality"
            ),
            headerBehavior: cloudfront.CacheHeaderBehavior.none(),
            cookieBehavior: cloudfront.CacheCookieBehavior.none(),
            defaultTtl: cdk.Duration.days(1),
            minTtl: cdk.Duration.minutes(1),
            maxTtl: cdk.Duration.days(365),
            enableAcceptEncodingGzip: true,
            enableAcceptEncodingBrotli: true,
        });

        this.cloudFront = new cloudfront.Distribution(this, "ImageResizeCF", {
            defaultBehavior: {
                origin,
                viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
                originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
                cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
            },
        });

        this.cloudFront.addBehavior("/images/*", origin, {
            viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
            cachePolicy: imageCachePolicy,
        });

        new cdk.CfnOutput(this, "CloudFrontDomain", {
            value: this.cloudFront.domainName,
        });
    }
}
