import {Discovery,configFromEnv} from './client.mjs';
try {console.log(JSON.stringify(await new Discovery(configFromEnv()).verify()));}
catch {console.error('Discovery HTTPS credential/workflow verification failed');process.exitCode=1;}
