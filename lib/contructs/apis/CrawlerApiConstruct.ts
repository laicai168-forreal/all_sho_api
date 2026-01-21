import { Construct } from "constructs"
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import { Function } from "aws-cdk-lib/aws-lambda";

interface CrawlerHelperApiConstructProps {
    crawlFunction: Function,
}

export class CrawlerHelperApiConstruct extends Construct {
    public readonly api: apigateway.RestApi;

    constructor(scope: Construct, id: string, props: CrawlerHelperApiConstructProps) {
        super(scope, id);

        const { crawlFunction } = props;
        this.api = new apigateway.RestApi(this, "CrawlerHelperApi", {
            restApiName: "Crawler Api Helpers",
            defaultCorsPreflightOptions: {
                allowOrigins: apigateway.Cors.ALL_ORIGINS,
                allowMethods: apigateway.Cors.ALL_METHODS,
            },
        });

        const crawl = this.api.root.addResource('crawl');

        crawl.addMethod("POST", new apigateway.LambdaIntegration(crawlFunction));
    }
}