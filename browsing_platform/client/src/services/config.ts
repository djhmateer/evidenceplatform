const serverPath = process.env.REACT_APP_SERVER_ENDPOINT || "http://localhost:4444/";

console.log(`[config] serverPath: ${serverPath}`);

const config = {serverPath}

export default config