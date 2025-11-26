// const auth_function = () => {
//     return {
//         'statusCode': 200,
//         'body': { message: 'Hello from Lambda!'}
//     }
// }
// export default { auth_function };

import { Handler } from "aws-cdk-lib/aws-lambda";
import jwt from 'jsonwebtoken';
import jwkToPem, { JWK } from 'jwk-to-pem';
import { CognitoJwtVerifier } from "aws-jwt-verify";

// A simple token-based authorizer example to demonstrate how to use an authorization token 
// to allow or deny a request. In this example, the caller named 'user' is allowed to invoke 
// a request if the client-supplied token value is 'allow'. The caller is not allowed to invoke 
// the request if the token value is 'deny'. If the token value is 'unauthorized' or an empty
// string, the authorizer function returns an HTTP 401 status code. For any other token value, 
// the authorizer returns an HTTP 500 status code. 
// Note that token values are case-sensitive.

export const handler: Handler =  async (event: any, context: any, callback: (arg1: any, arg2?: any) => void) => {
    const verifier = CognitoJwtVerifier.create({
        userPoolId: "us-east-1_Fin5RlUdn",
        tokenUse: "access",
        clientId: "6ja446jgvp1839q7tr624d4tc8",
    });
    const jwkUrl = 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Fin5RlUdn/.well-known/jwks.json';
    const jwks: JWK = {
        // "alg": "RS256",
        "e": "AQAB",
        // "kid": "9HJHuUB/q/9EHCBphXzGRGJphZJ+4OkrJsUoReWa7/g=",
        "kty": "RSA",
        "n": "tldvZ0UXZVP3soHANjqUYMtLOBlEqiXPU-q4cNLJDpw2USvzRNQ8-828IJZvECDc5VEJEfuP9YXXChfB3JHnJ7Ezrn6-hwvyvmnH0Yt7SfEBsizMf9dc5vm2OQ5ioBZhbxCUo7OEYt8Oejw67boe0if8n265FAOw5dvfIflCmmQS3_09-pCA_ZBShap-falorZVWLpZr9AMbEOC4HFiW-_ccBUVAiDf5bUduFc_43gTcSqZg6h9-ApWVjDhFjw1U7C6nxy6p8mmzQjaXcgMnpJ-EM6BVy7_ggls5aGRYH7LG51MW-CcczdNTxT_ea1hw9fb_JkYVB4NaxTmCAOCAfw",
        // "use": "sig"
    };

    // const jwks: JWK = {
    //     "keys": [
    //         {
    //             "alg": "RS256",
    //             "e": "AQAB",
    //             "kid": "9HJHuUB/q/9EHCBphXzGRGJphZJ+4OkrJsUoReWa7/g=",
    //             "kty": "RSA",
    //             "n": "tldvZ0UXZVP3soHANjqUYMtLOBlEqiXPU-q4cNLJDpw2USvzRNQ8-828IJZvECDc5VEJEfuP9YXXChfB3JHnJ7Ezrn6-hwvyvmnH0Yt7SfEBsizMf9dc5vm2OQ5ioBZhbxCUo7OEYt8Oejw67boe0if8n265FAOw5dvfIflCmmQS3_09-pCA_ZBShap-falorZVWLpZr9AMbEOC4HFiW-_ccBUVAiDf5bUduFc_43gTcSqZg6h9-ApWVjDhFjw1U7C6nxy6p8mmzQjaXcgMnpJ-EM6BVy7_ggls5aGRYH7LG51MW-CcczdNTxT_ea1hw9fb_JkYVB4NaxTmCAOCAfw",
    //             "use": "sig"
    //         },
    //         {
    //             "alg": "RS256",
    //             "e": "AQAB",
    //             "kid": "V/P0Skfn8NPgVHsaJEpLZQSuScxVhrzfSQYJ+JmZbCE=",
    //             "kty": "RSA",
    //             "n": "4LIaJJWpfJbFNZJncxFpJ_xp5LeS3xoXYxObH-sYyfXYusD7VeKzEZ_f-gMPhTFlLwgY4t7X5fC7Qc2WYyoRnLFgAm-trGqsuK2iqzTHHOm4zkraBLs8trboNEc1HBJl2ctNp-r_ES2C8TBCBY0GCAL9vOzjAn9LHISx9TdxglMgcjRxFpR12WE7NdU-6x-g_mCPz6cZjjUi_gM3jb0KOWuLKLY_5470n9SkM_rKMgufQ9-ikDTCRxdf-z8SAUQ8xS-zWJ-WCxzZTa87XhNkQsihSesJKPsa69qLlyiAidz0HgyEaeZCOWGsOQMqj3rjrrljAqiQZDcwIzryQsEEqw",
    //             "use": "sig"
    //         }
    //     ]
    // };

    // const authHeader = event.headers['authorization'];
    // if (!authHeader || !authHeader.startsWith('Bearer ')) {
    //     return {
    //         statusCode: 401,
    //         body: JSON.stringify({ message: 'Missing or invalid Authorization header' }),
    //     };
    // }

    const authHeader = event.authorizationToken;
    const token = authHeader.split(' ')[1];

    // const pem = jwkToPem(jwks)
    // return requestify.request(jwkUrl, { method: 'get', dataType: 'json' })
    //     .then(res => res.getBody()['keys'].shift())
    //     .then(jwk => jwkToPem(jwk))
    //     ;
    // jwt.verify(token, pem, { algorithms: ['RS256'] }, (err, decodedToken) => {
    //     if (err) {
    //         console.log(err);
    //         return {
    //             statusCode: 500,
    //             body: JSON.stringify({ message: 'Invalid Token' }),
    //         };
    //     }

    //     console.log(decodedToken);
    //     return {
    //         statusCode: 200,
    //         body: JSON.stringify({ message: decodedToken }),
    //     }
    // })

    // return {
    //     statusCode: 500,
    //     body: JSON.stringify({ message: 'Can not verify token' }),
    // };

    try {
        const payload = await verifier.verify(token);
        // callback(null, generatePolicy('user', 'Allow', event.methodArn));
        console.log("Token is valid. Payload:", payload);
        // return {
        //     statusCode: 200,
        //     body: JSON.stringify({ message: 'SUCCESS' }),
        // };
        return generatePolicy('user', 'Allow', event.methodArn);
    } catch {
        callback("Error: Invalid token");
        console.log("Token not valid!");
        return {
            statusCode: 401,
            body: JSON.stringify({ message: 'Invalid Token' }),
        };
    }

    // const token = authHeader.split(' ')[1];


    // try {
    //     const decoded = jwt.verify(token, JWT_SECRET);

    //     return {
    //         statusCode: 200,
    //         body: JSON.stringify({
    //             message: 'Authorized',
    //             user: decoded,
    //         }),
    //     };
    // } catch (err) {
    //     return {
    //         statusCode: 403,
    //         body: JSON.stringify({ message: 'Invalid token', error: (err as Error).message }),
    //     };
    // }

    // callback(null, generatePolicy('user', 'Allow', event.methodArn));
    // switch (token) {
    //     case 'allow':
    //         callback(null, generatePolicy('user', 'Allow', event.methodArn));
    //         break;
    //     case 'deny':
    //         callback(null, generatePolicy('user', 'Deny', event.methodArn));
    //         break;
    //     case 'unauthorized':
    //         callback("Unauthorized");   // Return a 401 Unauthorized response
    //         break;
    //     default:
    //         callback("Error: Invalid token"); // Return a 500 Invalid token response
    // }
};

// Help function to generate an IAM policy
var generatePolicy = (principalId: any, effect: any, resource: any) => {
    var authResponse: any = {};

    authResponse.principalId = principalId;
    if (effect && resource) {
        var policyDocument: any = {};
        policyDocument.Version = '2012-10-17';
        policyDocument.Statement = [];
        var statementOne: any = {};
        statementOne.Action = 'execute-api:Invoke';
        statementOne.Effect = effect;
        statementOne.Resource = resource;
        policyDocument.Statement[0] = statementOne;
        authResponse.policyDocument = policyDocument;
    }

    // Optional output with custom properties of the String, Number or Boolean type.
    authResponse.context = {
        "stringKey": "stringval",
        "numberKey": 123,
        "booleanKey": true
    };
    return authResponse;
}

