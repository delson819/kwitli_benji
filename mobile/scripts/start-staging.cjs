const net = require("node:net");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

const STAGING_API_URL = "https://api.kwitli.app";
const STAGING_ENV_MARKER = "EXPO_PUBLIC_KWITLI_ENV";
const STAGING_URL_VARIABLE = "EXPO_PUBLIC_STAGING_API_URL";
const METRO_PORT = 8090;
const mobileRoot = path.resolve(__dirname, "..");
const expoCli = path.join(mobileRoot, "node_modules", "expo", "bin", "cli");
const dotenvFiles = [".env", ".env.local", ".env.development", ".env.development.local"];

function assertStagingVariablesAreNotInDotenv(root = mobileRoot) {
  for (const file of dotenvFiles) {
    const filePath = path.join(root, file);
    let contents;
    try {
      contents = fs.readFileSync(filePath, "utf8");
    } catch (error) {
      if (error.code === "ENOENT") continue;
      throw new Error(`Unable to inspect Expo environment file ${file}.`);
    }
    for (const variable of [STAGING_ENV_MARKER, STAGING_URL_VARIABLE]) {
      if (new RegExp(`^\\s*(?:export\\s+)?${variable}\\s*=`, "m").test(contents)) {
        throw new Error(`Staging launch stopped: ${variable} must not be defined in ${file}; Expo dotenv values override process values in the app bundle.`);
      }
    }
  }
}

function createStagingEnvironment(parentEnvironment = process.env) {
  const environment = {
    ...parentEnvironment,
    [STAGING_ENV_MARKER]: "staging",
    [STAGING_URL_VARIABLE]: STAGING_API_URL,
  };
  if (environment[STAGING_ENV_MARKER] !== "staging" || environment[STAGING_URL_VARIABLE] !== STAGING_API_URL) {
    throw new Error("Unable to guarantee the staging API URL.");
  }
  return environment;
}

function startStaging() {
  try {
    assertStagingVariablesAreNotInDotenv();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
    return;
  }

  let server;
  try {
    server = net.createServer();
    server.once("error", (error) => {
      if (error.code === "EADDRINUSE") {
        console.error(`Staging launch stopped: Metro port ${METRO_PORT} is already in use. Stop the old Metro process first.`);
      } else {
        console.error(`Staging launch stopped: unable to verify the Metro port (${error.code ?? "unknown error"}).`);
      }
      process.exitCode = 1;
    });
    server.listen(METRO_PORT, () => {
      server.close(() => {
        const environment = createStagingEnvironment();
        console.log(`Starting Kwitli staging with API ${STAGING_API_URL} and Metro port ${METRO_PORT}.`);
        const expo = spawn(process.execPath, [expoCli, "start", "--clear", "--port", String(METRO_PORT)], {
          cwd: mobileRoot,
          env: environment,
          stdio: "inherit",
        });
        expo.once("error", () => {
          console.error("Staging launch stopped: Expo CLI could not be started.");
          process.exitCode = 1;
        });
        expo.once("exit", (code, signal) => {
          if (signal) process.kill(process.pid, signal);
          else process.exitCode = code ?? 1;
        });
      });
    });
  } catch (error) {
    console.error(`Staging launch stopped: unable to verify the Metro port (${error.code ?? "unknown error"}).`);
    process.exitCode = 1;
  }
}

if (require.main === module) startStaging();

module.exports = {
  METRO_PORT,
  STAGING_API_URL,
  STAGING_ENV_MARKER,
  STAGING_URL_VARIABLE,
  assertStagingVariablesAreNotInDotenv,
  createStagingEnvironment,
};
