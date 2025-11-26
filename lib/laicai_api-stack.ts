import * as cdk from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as log from 'aws-cdk-lib/aws-logs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambdaNodejs from 'aws-cdk-lib/aws-lambda-nodejs';
import { Construct } from 'constructs';
import path from 'path';
import { CrawlerConstruct } from './contructs/lambdas/crawlers/crawler';
import { CrawlerDatabaseConstruct } from './contructs/crawlerDB';
import { CrawlerBucketConstruct } from './contructs/crawlerBucket';
import { CarApi } from './contructs/lambdas/cars/car-api';
import { UserItemDatabaseConstruct } from './contructs/tables/user-item';
import { AddCollectionConstruct } from './contructs/lambdas/collections/AddCollectionConstruct';
import { GetCollectionConstruct } from './contructs/lambdas/collections/GetCollectionConstruct';
import { DeleteCollectionConstruct } from './contructs/lambdas/collections/DeleteCollectionConstruct';
import { AddtionalCarDataPopulatorConstruct } from './contructs/lambdas/crawlers/AddtionalCarDataConstruct';

export class LaicaiApiStack extends cdk.Stack {
	constructor(scope: Construct, id: string, props?: cdk.StackProps) {
		super(scope, id, props);

		const logger = new log.LogGroup(this, 'api-gateway-logger', {
			retention: log.RetentionDays.ONE_WEEK,
			removalPolicy: cdk.RemovalPolicy.DESTROY,
		});

		const api = new apigw.RestApi(this, 'laicai-api', {
			deployOptions: {
				loggingLevel: apigw.MethodLoggingLevel.INFO,
				accessLogDestination: new apigw.LogGroupLogDestination(logger),
				dataTraceEnabled: true,
				accessLogFormat: apigw.AccessLogFormat.jsonWithStandardFields(),
			},
		});

		api.root.addMethod('ANY');

		// create a Lambda function for API Gateway to invoke
		const lambdaFn = new lambda.Function(this, "lambdaFn", {
			code: lambda.Code.fromAsset(path.join(__dirname, "../lambda")),
			runtime: lambda.Runtime.NODEJS_LATEST,
			timeout: cdk.Duration.seconds(40),
			handler: "test.handler",
		});

		// capturing architecture for docker container (arm or x86)
		// const dockerPlatform = process.env["DOCKER_CONTAINER_PLATFORM_ARCH"]

		// // Authorizer function for JWT tokens
		// const dockerfile = path.join(__dirname, "../lambda/dockerized-jwt-auth-function/");
		// const code = lambda.Code.fromAssetImage(dockerfile);

		const jwtAuthLayeredFn = new lambdaNodejs.NodejsFunction(this, "jwtAuthLayeredFn", {
			// code: lambda.Code.fromAsset(path.join(__dirname, "../lambda")),
			// runtime: lambda.Runtime.NODEJS_LATEST,
			entry: path.join(__dirname, '../lambda/jwt-auth-function.ts'),
			timeout: cdk.Duration.seconds(40),
			handler: "handler",
			// architecture: dockerPlatform == "arm" ? lambda.Architecture.ARM_64 : lambda.Architecture.X86_64,
			environment: {
				"API_ID": api.restApiId,
				"API_REGION": this.region,
				"ACCOUNT_ID": this.account,
				"COGNITO_USER_POOL_ID": 'us-east-1_Fin5RlUdn',
				"COGNITO_APP_CLIENT_ID": '6ja446jgvp1839q7tr624d4tc8'
			}
		});

		// create JWT token authorizer for the API Gateway endpoint
		const tokenAuthorizer = new apigw.TokenAuthorizer(this, 'jwttokenAuth', {
			handler: jwtAuthLayeredFn,
			validationRegex: "^(Bearer )[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+?\.([a-zA-Z0-9\-_]+)$",
		});

		// create a GET /hello endpoint which invoked the simple lambda function,
		// and uses the token authorizer created above
		const testEndpoint = api.root.addResource('test');
		const methodResponse1: cdk.aws_apigateway.MethodResponse = {
			statusCode: "200",

			// the properties below are optional
			// responseModels: {
			// 	responseModelsKey: cdk.aws_apigateway.Model,
			// },
			// responseParameters: {
			// 	responseParametersKey: false,
			// },
		}
		testEndpoint.addMethod(
			"GET",
			new apigw.LambdaIntegration(lambdaFn, {
				proxy: true,
			}),
			// new apigw.LambdaIntegration(lambdaFn),
			{
				authorizer: tokenAuthorizer,
				methodResponses: [
					{ statusCode: "200" },
					{ statusCode: "401" },
					{ statusCode: "403" },
					{ statusCode: "500" },
				]
			}
		);

		const userItemTable = new UserItemDatabaseConstruct(this, 'UserItemTable');
		const addCollectionFunction = new AddCollectionConstruct(this, 'UCAdd', { table: userItemTable.table });
		const getCollectionFunction = new GetCollectionConstruct(this, 'UCGet', { table: userItemTable.table });
		const deleteCollectionFunction = new DeleteCollectionConstruct(this, 'UCDelete', { table: userItemTable.table });
		const userItemApi = new apigw.RestApi(this, "CollectionsApi", {
			restApiName: "User Collections Service",
			defaultCorsPreflightOptions: {
				allowOrigins: apigw.Cors.ALL_ORIGINS,
				allowMethods: apigw.Cors.ALL_METHODS,
			},
		});

		const collections = userItemApi.root.addResource("collections");

		// collections
		collections.addMethod("POST", new apigw.LambdaIntegration(addCollectionFunction.function));
		collections.addMethod("GET", new apigw.LambdaIntegration(getCollectionFunction.function));
		collections.addMethod("DELETE", new apigw.LambdaIntegration(deleteCollectionFunction.function))

		new cdk.CfnOutput(this, 'user item api', {
			value: userItemApi.url ?? 'No URL',
		});

		// VPC
		const vpc = new ec2.Vpc(this, 'CarsVpc', {
			maxAzs: 2,
		});

		// DB credentials secret
		const secret = new secretsmanager.Secret(this, 'DbCredentials', {
			secretName: 'cars/db-credentials',
			generateSecretString: {
				secretStringTemplate: JSON.stringify({ username: 'firstuser' }),
				generateStringKey: 'password',
				excludeCharacters: '/@",  '
			},
		});

		const cluster = new rds.DatabaseCluster(this, 'CarsAurora', {
			engine: rds.DatabaseClusterEngine.auroraPostgres({
				version: rds.AuroraPostgresEngineVersion.VER_14_17,
			}),
			instances: 1,
			credentials: rds.Credentials.fromGeneratedSecret('dbadmin'),
			instanceProps: {
				vpc,
				vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
				instanceType: ec2.InstanceType.of(
					ec2.InstanceClass.R6G, // Aurora-compatible
					ec2.InstanceSize.LARGE
				),
			},
			defaultDatabaseName: 'carsdb',
		});

		const dbSecret = cluster.secret!;

		const crawlerDB = new CrawlerDatabaseConstruct(this, 'CrawlerDB');
		const crawlerBucket = new CrawlerBucketConstruct(this, 'CrawlerBucket');
		const crawlerFunction = new CrawlerConstruct(this, 'Crawler', { table: crawlerDB.table, bucket: crawlerBucket.bucket, secret: dbSecret, vpc: vpc });

		// Addtional car data populator lambda
		const addtionalCarDataPopulatorFunction = new AddtionalCarDataPopulatorConstruct(this, 'AddtionalCarDataPopulator', { table: crawlerDB.table, bucket: crawlerBucket.bucket, secret: dbSecret, vpc: vpc });

		// Lambda role & function
		const fnRole = new iam.Role(this, 'CrawlerRole', {
			assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
		});

		// allow log and secret access & s3 put:
		fnRole.addManagedPolicy(iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'));
		// secret.grantRead(fnRole);
		// rawBucket.grantPut(fnRole);

		// Allow security group access to the DB cluster
		cluster.connections.allowDefaultPortFromAnyIpv4(); // tighten for production

		crawlerDB.table.grantReadWriteData(crawlerFunction.function);

		const crawlerAPI = new apigw.RestApi(this, 'CrawlerAPI', {
			restApiName: 'Crawler Service',
		});

		const crawlerIntegration = new apigw.LambdaIntegration(crawlerFunction.function);
		crawlerAPI.root.addResource('run').addMethod('POST', crawlerIntegration);

		// allow lambda to connect to the DB
		cluster.grantDataApiAccess(fnRole); // if using Data API
		// If not using Data API, make sure SecurityGroups allow Lambda to reach DB endpoint.

		const carApi = new CarApi(this, 'CarApiConstruct', { dynamoTable: crawlerDB.table, userCollectionTable: userItemTable.table, secret: dbSecret, vpc: vpc });

		new cdk.CfnOutput(this, 'ApiUrl', {
			value: carApi.api.url ?? 'No URL',
		});
	}
}
