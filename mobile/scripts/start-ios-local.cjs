const { execFileSync, spawn } = require("node:child_process");
const { existsSync } = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const port = Number(process.env.KWITLI_EXPO_PORT ?? 8081);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("KWITLI_EXPO_PORT doit etre un port valide.");
}

function run(command, args) {
  return execFileSync(command, args, { encoding: "utf8" }).trim();
}

function chooseSimulator() {
  const { devices } = JSON.parse(run("xcrun", ["simctl", "list", "devices", "available", "--json"]));
  const iphones = Object.entries(devices)
    .filter(([runtime]) => runtime.includes("SimRuntime.iOS-"))
    .flatMap(([, entries]) => entries)
    .filter((device) => device.isAvailable && device.name.startsWith("iPhone"));
  const requested = process.env.KWITLI_IOS_DEVICE;
  const device = requested
    ? iphones.find((entry) => entry.udid === requested || entry.name === requested)
    : iphones.find((entry) => entry.name === "iPhone 17 Pro" && entry.state === "Booted")
      ?? iphones.find((entry) => entry.state === "Booted")
      ?? iphones.find((entry) => entry.name === "iPhone 17 Pro")
      ?? iphones[0];
  if (!device) throw new Error("Aucun simulateur iPhone disponible dans Xcode.");
  return device;
}

function metroReady() {
  return new Promise((resolve) => {
    const request = http.get(`http://127.0.0.1:${port}/status`, { timeout: 2000 }, (response) => {
      let body = "";
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => resolve(response.statusCode === 200 && body.trim() === "packager-status:running"));
    });
    request.on("error", () => resolve(false));
    request.on("timeout", () => request.destroy());
  });
}

async function main() {
  if (process.platform !== "darwin") throw new Error("Ce lanceur necessite macOS et Xcode 27.");
  const developerDir = run("xcode-select", ["-p"]);
  const deviceHub = path.join(path.dirname(developerDir), "Applications", "DeviceHub.app");
  if (!existsSync(deviceHub)) throw new Error(`Device Hub introuvable : ${deviceHub}`);

  const simulator = chooseSimulator();
  if (simulator.state !== "Booted") {
    console.log(`Demarrage de ${simulator.name}...`);
    run("xcrun", ["simctl", "boot", simulator.udid]);
    run("xcrun", ["simctl", "bootstatus", simulator.udid, "-b"]);
  }
  run("open", ["-a", deviceHub]);

  const openKwitli = () => {
    run("xcrun", ["simctl", "openurl", simulator.udid, `exp://127.0.0.1:${port}`]);
    console.log(`Kwitli ouvert dans ${simulator.name} via Device Hub.`);
  };
  if (await metroReady()) {
    console.log(`Metro fonctionne deja sur le port ${port}.`);
    openKwitli();
    return;
  }

  const expo = path.join(__dirname, "..", "node_modules", ".bin", "expo");
  if (!existsSync(expo)) throw new Error("Expo est absent. Executez npm install dans mobile/.");
  const child = spawn(expo, ["start", "--clear", "--localhost", "--go", "--port", String(port)], {
    cwd: path.join(__dirname, ".."), stdio: "inherit",
  });
  let childExit;
  child.on("exit", (code) => { childExit = code ?? 1; });
  child.on("error", (error) => { childExit = 1; console.error(`Expo: ${error.message}`); });
  try {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      if (childExit !== undefined) throw new Error(`Expo s'est arrêté avant le lancement (code ${childExit}).`);
      if (await metroReady()) {
        openKwitli();
        process.exitCode = childExit !== undefined
          ? childExit
          : await new Promise((resolve) => child.once("exit", (code) => resolve(code ?? 1)));
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error("Metro n'a pas répondu sur le port attendu après 60 secondes.");
  } catch (error) {
    child.kill("SIGTERM");
    throw error;
  }
}

main().catch((error) => {
  console.error(`Lancement iOS impossible : ${error.message}`);
  process.exitCode = 1;
});
