import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { AdditionalDataHelperApiConstruct } from './contructs/apis/AdditionalDataHelperApiConstruct';
import { CrawlerHelperApiConstruct } from './contructs/apis/CrawlerApiConstruct';
import { CrawlerLoggingConstruct } from './contructs/apis/CrawlerLoggingConstruct';
import { HttpApiConstruct } from './contructs/apis/HttpApiConstruct';
import { UserFastApiConstruct } from './contructs/apis/UserFastApiConstruct';
import { ImageResizeCfnConstruct } from './contructs/cloudFront/ImageResizeCfnConstruct';
import { CarsDynamoConstruct } from './contructs/dynamos/CarsDynamoConstruct';
import { LikeCollectionDynamoConstruct } from './contructs/dynamos/LikeCollectionDynamoConstruct';
import { UserCollectionDynamoConstruct } from './contructs/dynamos/UserCollectionDynamoConstruct';
import { AddCollectionConstruct } from './contructs/lambdas/collections/AddCollectionConstruct';
import { DeleteCollectionConstruct } from './contructs/lambdas/collections/DeleteCollectionConstruct';
import { DislikeCollectionConstruct } from './contructs/lambdas/collections/DislikeCollectionConstruct';
import { GetCollectionConstruct } from './contructs/lambdas/collections/GetCollectionConstruct';
import { LikeCollectionConstruct } from './contructs/lambdas/collections/LikeCollectionConstruct';
import { AddtionalCarDataPopulatorConstruct } from './contructs/lambdas/crawlers/AddtionalCarDataConstruct';
import { CrawlerConstruct } from './contructs/lambdas/crawlers/CarCrawlerConstruct';
import { InnoCrawlerConstruct } from './contructs/lambdas/crawlers/InnoCrawlerConstruct';
import { PopRaceCrawlerConstruct } from './contructs/lambdas/crawlers/PopRaceCrawlerConstruct';
import { TWCrawlerConstruct } from './contructs/lambdas/crawlers/TWCrawlerConstruct';
import { ImagesResizingLambdaConstruct } from './contructs/lambdas/images/ImagesResizingLambdaConstruct';
import { CommonLayerConstruct } from './contructs/layers/CommonLayerConstruct';
import { CarsRDSInstanceConstruct } from './contructs/rds/CarsRDSInstanceConstruct';
import { CrawlerBucketConstruct } from './contructs/s3/crawlerBucket';
import { ProfileImageBucketConstruct } from './contructs/s3/ProfileImageBucketConstruct';
import { CarsDataVpcConstruct } from './contructs/vpc/CarsDataVpcConstruct';

export class LaicaiApiStack extends cdk.Stack {
	constructor(scope: Construct, id: string, props?: cdk.StackProps) {
		super(scope, id, props);

		const cognitoUserPoolId =
			process.env.COGNITO_USER_POOL_ID ||
			process.env.REACT_APP_COGNITO_USER_POOL_ID ||
			'us-east-1_ZZtovbzxr';
		const cognitoAppClientId =
			process.env.COGNITO_APP_CLIENT_ID ||
			process.env.REACT_APP_COGNITO_CLIENT_ID ||
			'1rfcnq8a774inv07a9rlmp3vnd';

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
		const { function: getCollectionFunction } = new GetCollectionConstruct(this, 'UCGet', { carRDSInstance, secret: dbSecret, vpc: carsVpc });
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
		const { function: minigtCrawlFunction } = new CrawlerConstruct(this, 'Crawler', { bucket: crawlerBucket.bucket, secret: dbSecret, vpc: carsVpc, carRDSInstance, logsTable });
		const { function: tarmacworksCrawlFunction } = new TWCrawlerConstruct(this, 'CrawlerTW', { bucket: crawlerBucket.bucket, secret: dbSecret, vpc: carsVpc, carRDSInstance, logsTable });
		const { function: innoCrawlFunction } = new InnoCrawlerConstruct(this, 'CrawlerInno', { bucket: crawlerBucket.bucket, secret: dbSecret, vpc: carsVpc, carRDSInstance, logsTable });
		const { function: popraceCrawlerFunction } = new PopRaceCrawlerConstruct(this, 'CrawlerPoprace', { bucket: crawlerBucket.bucket, secret: dbSecret, vpc: carsVpc, carRDSInstance, logsTable });
		new CrawlerHelperApiConstruct(this, 'CrawlerHelperApi', { minigtCrawlFunction, tarmacworksCrawlFunction, innoCrawlFunction, popraceCrawlerFunction });
		const { function: addtionalDataFunction } = new AddtionalCarDataPopulatorConstruct(this, 'AddtionalCarDataPopulator', { bucket: crawlerBucket.bucket, secret: dbSecret, vpc: carsVpc, carRDSInstance, logsTable });
		new AdditionalDataHelperApiConstruct(this, 'AddtionalDataHelperApi', { addtionalDataFunction });

		///////////////////////////////////////////////////////////////
		// Image stack
		const imageResizeLambda = new ImagesResizingLambdaConstruct(this, 'ImageResizingLambda', { imageBucket: crawlerBucket.bucket, oldBucket: crawlerBucket.oldBucket });
		new ImageResizeCfnConstruct(this, 'ImageResizeCfn', { imageResizeFunctionUrl: imageResizeLambda.functionUrl.url });

		///////////////////////////////////////////////////////////////
		// Http stack
		const httpApiConstruct = new HttpApiConstruct(this, "HttpApiConstruct", {
			addCollectionFn: addCollectionFunction,
			deleteCollectionFn: deleteCollectionFunction,
			likeCollectionFn: likeCollectionFunction,
			dislikeCollectionFn: dislikeCollectionFunction,
			getCollectionFn: getCollectionFunction,
			userPoolId: cognitoUserPoolId,
			appClientId: cognitoAppClientId,
		});

		new cdk.CfnOutput(this, "UserCollectionsHttpApiUrl", {
			value: httpApiConstruct.httpApi.url || "Found URL for http api",
			exportName: "UserCollectionsHttpApiUrl",
		});

		/////////////////////////////////////////////////////////////
		// Lambda layer stack
		const { layer: commonLayer } = new CommonLayerConstruct(this, "CommonLayer");

		// User constructs
		const profileImageBucket = new ProfileImageBucketConstruct(this, 'ProfileImageBucket');

		////////////////////////////////////////////////////
		// Backend API stack with FastAPI, will use the same authorizer and http api as the user collection stack, and connect to the same RDS instance, but in a different lambda function, which is more flexible for future development
		new UserFastApiConstruct(this, "UserFastApi", {
			httpApi: httpApiConstruct.httpApi,
			authorizer: httpApiConstruct.authorizer,
			vpc: carsVpc,
			rds: carRDSInstance,
			dbSecret: dbSecret,
			layer: commonLayer, // your existing lambda layer
			profileImageBucket: profileImageBucket.bucket,
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
