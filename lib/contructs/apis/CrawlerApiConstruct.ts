import { Construct } from "constructs"
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import { Function } from "aws-cdk-lib/aws-lambda";

interface CrawlerHelperApiConstructProps {
    minigtCrawlFunction: Function,
    tarmacworksCrawlFunction: Function,
    innoCrawlFunction: Function,
    popraceCrawlerFunction: Function,
}

export class CrawlerHelperApiConstruct extends Construct {
    public readonly api: apigateway.RestApi;

    constructor(scope: Construct, id: string, props: CrawlerHelperApiConstructProps) {
        super(scope, id);

        const {
            minigtCrawlFunction,
            tarmacworksCrawlFunction,
            innoCrawlFunction,
            popraceCrawlerFunction,
        } = props;

        this.api = new apigateway.RestApi(this, "CrawlerHelperApi", {
            restApiName: "Crawler Api Helpers",
            defaultCorsPreflightOptions: {
                allowOrigins: apigateway.Cors.ALL_ORIGINS,
                allowMethods: apigateway.Cors.ALL_METHODS,
            },
        });

        const crawlMinigt = this.api.root.addResource('crawl_minigt');
        const crawlTarmacworks = this.api.root.addResource('crawl_tarmacworks');
        const crawlInno = this.api.root.addResource('crawl_inno');
        const crawPoprace = this.api.root.addResource('crawl_poprace');

        crawlMinigt.addMethod("POST", new apigateway.LambdaIntegration(minigtCrawlFunction));
        crawlTarmacworks.addMethod("POST", new apigateway.LambdaIntegration(tarmacworksCrawlFunction));
        crawlInno.addMethod("POST", new apigateway.LambdaIntegration(innoCrawlFunction));
        crawPoprace.addMethod("POST", new apigateway.LambdaIntegration(popraceCrawlerFunction));
    }
}