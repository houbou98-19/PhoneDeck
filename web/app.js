// The page: connect, show CPU and RAM, and a button that locks the computer.

import { PhoneDeckLink } from "./ble.js";
import { Kind, Status } from "./protocol.js";

const $ = (id) => document.getElementById(id);
const link = new PhoneDeckLink();
let refreshTimer = null;

// The service UUID can come in the address, like  https://.../#277cedef-a9df-...
// (the same way the QR code will carry it later). The fragment never goes to the server.
$("service").value = location.hash.slice(1);

function log(text) {
  const time = new Date().toLocaleTimeString();
  $("log").textContent = `${time}  ${text}\n` + $("log").textContent;
}

function setConnected(connected) {
  $("status").textContent = connected ? "Connected" : "Not connected";
  $("status").dataset.state = connected ? "on" : "off";
  $("connect").hidden = connected;
  $("service-row").hidden = connected;
  $("deck").hidden = !connected;
  $("disconnect").hidden = !connected;
}

/** Ask the computer for a percentage and show it in a gauge. */
async function refresh(name, label) {
  const { status, data } = await link.request(Kind.QUERY, name);
  if (status !== Status.OK) throw new Error(`${name}: status ${status}`);
  const percent = data[0];
  $(`${name}-value`).textContent = `${percent} %`;
  $(`${name}-bar`).value = percent;
  return label;
}

async function refreshAll() {
  try {
    await refresh("cpu", "CPU");
    await refresh("ram", "RAM");
  } catch (error) {
    log(`Could not read: ${error.message}`);
  }
}

function startRefreshing() {
  refreshAll();
  refreshTimer = setInterval(refreshAll, 2000);
}

function stopRefreshing() {
  clearInterval(refreshTimer);
  refreshTimer = null;
}

$("connect").addEventListener("click", async () => {
  const serviceUuid = $("service").value.trim();
  if (!serviceUuid) {
    log("Paste the service UUID that PhoneDeck prints on the computer.");
    return;
  }
  try {
    log("Choose the computer in the list...");
    await link.connect(serviceUuid);
    setConnected(true);
    log("Connected.");
    startRefreshing();
  } catch (error) {
    log(`Could not connect: ${error.message}`);
  }
});

$("disconnect").addEventListener("click", () => link.disconnect());

$("lock").addEventListener("click", async () => {
  try {
    const { status } = await link.request(Kind.COMMAND, "lock");
    log(status === Status.OK ? "The computer is locked." : `Lock failed (status ${status}).`);
  } catch (error) {
    log(`Lock failed: ${error.message}`);
  }
});

link.onDisconnect = () => {
  stopRefreshing();
  setConnected(false);
  log("Disconnected.");
};

if (!("bluetooth" in navigator)) {
  log("This browser has no Web Bluetooth. Use Chrome on Android.");
  $("connect").disabled = true;
}
setConnected(false);
