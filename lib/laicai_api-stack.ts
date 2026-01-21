import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { CrawlerConstruct } from './contructs/lambdas/crawlers/CarCrawlerConstruct';
import { CarsDynamoConstruct } from './contructs/dynamos/CarsDynamoConstruct';
import { CrawlerBucketConstruct } from './contructs/s3/crawlerBucket';
import { CarApi } from './contructs/lambdas/cars/CarsApiConstruct';
import { UserCollectionDynamoConstruct } from './contructs/dynamos/UserCollectionDynamoConstruct';
import { AddCollectionConstruct } from './contructs/lambdas/collections/AddCollectionConstruct';
import { GetCollectionConstruct } from './contructs/lambdas/collections/GetCollectionConstruct';
import { DeleteCollectionConstruct } from './contructs/lambdas/collections/DeleteCollectionConstruct';
import { AddtionalCarDataPopulatorConstruct } from './contructs/lambdas/crawlers/AddtionalCarDataConstruct';
import { ImagesResizingLambdaConstruct } from './contructs/lambdas/images/ImagesResizingLambdaConstruct';
import { ImageResizeCfnConstruct } from './contructs/cloudFront/ImageResizeCfnConstruct';
import { ImageResizeApiConstruct } from './contructs/apis/ImageResizeApiConstruct';
import { CarsRDSInstanceConstruct } from './contructs/rds/CarsRDSInstanceConstruct';
// import { UserCollectionApiConstruct } from './contructs/apis/UserCollectionApiConstruct';
import { JWTAuthConstruct } from './contructs/lambdas/auth/JWTAuthConstruct';
import { AuthApiConstruct } from './contructs/apis/AuthApiConstruct';
import { CarsDataVpcConstruct } from './contructs/vpc/CarsDataVpcConstruct';
import { JWTAuthorizerConstruct } from './contructs/apis/JWTAuthorizerConstruct';
import { CrawlerHelperApiConstruct } from './contructs/apis/CrawlerApiConstruct';
import { CrawlerLoggingConstruct } from './contructs/apis/CrawlerLoggingConstruct';
import { AdditionalDataHelperApiConstruct } from './contructs/apis/AdditionalDataHelperApiConstruct';
import { LikeCollectionConstruct } from './contructs/lambdas/collections/LikeCollectionConstruct';
import { LikeCollectionDynamoConstruct } from './contructs/dynamos/LikeCollectionDynamoConstruct';
import { DislikeCollectionConstruct } from './contructs/lambdas/collections/DislikeCollectionConstruct';
import { HttpApiConstruct } from './contructs/apis/HttpApiConstruct';

export class LaicaiApiStack extends cdk.Stack {
	constructor(scope: Construct, id: string, props?: cdk.StackProps) {
		super(scope, id, props);



		// ///////////////////////////////////////////////////////////////
		// // Authorizer
		// const { api: authApi } = new AuthApiConstruct(this, 'AuthApi');
		// const { function: jwtAuthLayeredFn } = new JWTAuthConstruct(this, 'JWTAuthLayeredFn', { authApiGateway: authApi, region: this.region, account: this.account });
		// const { authorizer } = new JWTAuthorizerConstruct(this, 'JWTAuthorizer', { jwtAuthLayeredFn });

		///////////////////////////////////////////////////////////////
		// Higher level
		const { vpc: carsVpc } = new CarsDataVpcConstruct(this, 'CarsVPCV2');
		const { instance: carRDSInstance } = new CarsRDSInstanceConstruct(this, 'CarsRDS', { vpc: carsVpc });
		const dbSecret = carRDSInstance.secret!;

		///////////////////////////////////////////////////////////////
		// User collection stack
		const userItemTable = new UserCollectionDynamoConstruct(this, 'UserItemTable');
		const likeItemTable = new LikeCollectionDynamoConstruct(this, 'LikeItemTable');
		const { function: addCollectionFunction } = new AddCollectionConstruct(this, 'UCAdd', { carRDSInstance, secret: dbSecret, vpc: carsVpc });
		const { function: getCollectionFunction } = new GetCollectionConstruct(this, 'UCGet', { table: userItemTable.table });
		const { function: deleteCollectionFunction } = new DeleteCollectionConstruct(this, 'UCDelete', { carRDSInstance, secret: dbSecret, vpc: carsVpc });
		const { function: likeCollectionFunction } = new LikeCollectionConstruct(this, 'UCLike', { carRDSInstance, secret: dbSecret, vpc: carsVpc });
		const { function: dislikeCollectionFunction } = new DislikeCollectionConstruct(this, 'UCDislike', { carRDSInstance, secret: dbSecret, vpc: carsVpc });
		// const { api: userItemApi } = new UserCollectionApiConstruct(
		// 	this,
		// 	'UserCollectionApi',
		// 	{
		// 		addCollectionFunction,
		// 		getCollectionFunction,
		// 		deleteCollectionFunction,
		// 		likeCollectionFunction,
		// 		dislikeCollectionFunction,
		// 		authorizer,
		// 	});
		// new cdk.CfnOutput(this, 'user item api', {
		// 	value: userItemApi.url ?? 'No URL',
		// });

		// Crawler stack
		const carsDynamo = new CarsDynamoConstruct(this, 'CrawlerDB');
		const crawlerBucket = new CrawlerBucketConstruct(this, 'CrawlerBucket');
		const { logsTable } = new CrawlerLoggingConstruct(this, 'CrawlerLog');
		const { function: crawlerFunction } = new CrawlerConstruct(this, 'Crawler', { bucket: crawlerBucket.bucket, secret: dbSecret, vpc: carsVpc, carRDSInstance, logsTable });
		new CrawlerHelperApiConstruct(this, 'CrawlerHelperApi', { crawlFunction: crawlerFunction });
		const { function: addtionalDataFunction } = new AddtionalCarDataPopulatorConstruct(this, 'AddtionalCarDataPopulator', { bucket: crawlerBucket.bucket, secret: dbSecret, vpc: carsVpc, carRDSInstance, logsTable });
		new AdditionalDataHelperApiConstruct(this, 'AddtionalDataHelperApi', { addtionalDataFunction });

		///////////////////////////////////////////////////////////////
		// Image stack
		const imageResizeLambda = new ImagesResizingLambdaConstruct(this, 'ImageResizingLambda', { imageBucket: crawlerBucket.bucket, oldBucket: crawlerBucket.oldBucket });
		new ImageResizeCfnConstruct(this, 'ImageResizeCfn', { imageResizeFunctionUrl: imageResizeLambda.functionUrl.url });

		///////////////////////////////////////////////////////////////
		// Car stack
		new CarApi(
			this,
			'CarApiConstruct',
			{
				userCollectionTable: userItemTable.table,
				likeCollectionTable: likeItemTable.table,
				secret: dbSecret,
				vpc: carsVpc,
				rds: carRDSInstance
			});

		///////////////////////////////////////////////////////////////
		// Http stack
		const httpApiConstruct = new HttpApiConstruct(this, "HttpApiConstruct", {
			addCollectionFn: addCollectionFunction,
			deleteCollectionFn: deleteCollectionFunction,
			likeCollectionFn: likeCollectionFunction,
			dislikeCollectionFn: dislikeCollectionFunction,
			userPoolId: "us-east-1_Fin5RlUdn",
			appClientId: "6ja446jgvp1839q7tr624d4tc8",
		});
		new cdk.CfnOutput(this, "UserCollectionsHttpApiUrl", {
			value: httpApiConstruct.httpApi.url || "Found URL for http api",
			exportName: "UserCollectionsHttpApiUrl",
		});

		//////////////////////////////////////////////////////////////
		// An example of jwt auth for function, will apply this 
		// create a GET /hello endpoint which invoked the simple lambda function,
		// and uses the token authorizer created above
		// create a Lambda function for API Gateway to invoke
		// const lambdaFn = new lambda.Function(this, "lambdaFn", {
		// 	code: lambda.Code.fromAsset(path.join(__dirname, "../lambda")),
		// 	runtime: lambda.Runtime.NODEJS_LATEST,
		// 	timeout: cdk.Duration.seconds(40),
		// 	handler: "test.handler",
		// });
		// const testEndpoint = authApi.root.addResource('test');
		// const methodResponse1: cdk.aws_apigateway.MethodResponse = {
		// 	statusCode: "200",

		// 	// the properties below are optional
		// 	// responseModels: {
		// 	// 	responseModelsKey: cdk.aws_apigateway.Model,
		// 	// },
		// 	// responseParameters: {
		// 	// 	responseParametersKey: false,
		// 	// },
		// }
		// testEndpoint.addMethod(
		// 	"GET",
		// 	new apigw.LambdaIntegration(lambdaFn, {
		// 		proxy: true,
		// 	}),
		// 	// new apigw.LambdaIntegration(lambdaFn),
		// 	{
		// 		authorizer: tokenAuthorizer,
		// 		methodResponses: [
		// 			{ statusCode: "200" },
		// 			{ statusCode: "401" },
		// 			{ statusCode: "403" },
		// 			{ statusCode: "500" },
		// 		]
		// 	}
		// );

		// may not need this
		// const fnRole = new iam.Role(this, 'CrawlerRole', {
		// 	assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
		// });
		// // allow log and secret access & s3 put:
		// fnRole.addManagedPolicy(iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'));
		// // secret.grantRead(fnRole);
		// // rawBucket.grantPut(fnRole);
		// carRDSInstance.connections.allowDefaultPortFromAnyIpv4();

		// made to expose the crawler, may not need for now, less priority
		// Lambda role & function
		// crawlerDB.table.grantReadWriteData(crawlerFunction.function);
		// const crawlerAPI = new apigw.RestApi(this, 'CrawlerAPI', {
		// 	restApiName: 'Crawler Service',
		// });
		// const crawlerIntegration = new apigw.LambdaIntegration(crawlerFunction.function);
		// crawlerAPI.root.addResource('run').addMethod('POST', crawlerIntegration);
	}
}
