// Web Bluetooth: the phone's side of the BLE link to the computer.
//
// The computer is the peripheral. This page is the central: it finds the computer by its
// service UUID, writes requests to the write characteristic, and listens for responses on the
// notify characteristic. A request and its response are matched by the request id.
//
// This file needs a real phone and a real computer, so it has no tests.

import {
  Kind,
  MAX_REQUEST_ID,
  ProtocolError,
  characteristicUuids,
  decodeMessage,
  encodeMessage,
  parseResponseBody,
} from "./protocol.js";

const REQUEST_TIMEOUT_MS = 5000;

export class PhoneDeckLink {
  #device = null;
  #write = null;
  #pending = new Map(); // request id -> { resolve, reject, timer }
  #nextRequestId = 1;

  /** Called when the link goes down (the computer went away, or disconnect() was called). */
  onDisconnect = () => {};

  get connected() {
    return this.#device?.gatt?.connected === true;
  }

  /**
   * Let the user pick the computer in Chrome's chooser, connect, and start listening.
   * Must be called from a click, because Web Bluetooth requires a user gesture.
   */
  async connect(serviceUuid) {
    const { write, notify } = await characteristicUuids(serviceUuid);

    this.#device = await navigator.bluetooth.requestDevice({
      filters: [{ services: [serviceUuid] }],
    });
    this.#device.addEventListener("gattserverdisconnected", () => this.#handleDisconnect());

    const server = await this.#device.gatt.connect();
    const service = await server.getPrimaryService(serviceUuid);
    this.#write = await service.getCharacteristic(write);
    const notifyCharacteristic = await service.getCharacteristic(notify);

    notifyCharacteristic.addEventListener("characteristicvaluechanged", (event) =>
      this.#handleNotification(event.target.value),
    );
    await notifyCharacteristic.startNotifications();
  }

  /**
   * Send a request and wait for its response.
   * @param {number} kind Kind.COMMAND or Kind.QUERY
   * @param {string} name the action, for example "lock" or "cpu"
   * @returns {Promise<{status: number, data: Uint8Array}>}
   */
  async request(kind, name) {
    if (!this.connected) throw new Error("Not connected");

    const requestId = this.#nextRequestId;
    this.#nextRequestId = (requestId % MAX_REQUEST_ID) + 1; // 1, 2, ... 65535, 1, ...

    const response = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#pending.delete(requestId);
        reject(new Error(`No answer to "${name}" within ${REQUEST_TIMEOUT_MS / 1000} s`));
      }, REQUEST_TIMEOUT_MS);
      this.#pending.set(requestId, { resolve, reject, timer });
    });

    try {
      const packet = encodeMessage(kind, requestId, new TextEncoder().encode(name));
      await this.#write.writeValueWithResponse(packet);
    } catch (error) {
      this.#settle(requestId, (pending) => pending.reject(error));
      throw error;
    }
    return response;
  }

  disconnect() {
    if (this.connected) this.#device.gatt.disconnect();
  }

  // --- internals ---

  #handleNotification(view) {
    let message;
    try {
      // The DataView from Web Bluetooth may be a window into a bigger buffer.
      message = decodeMessage(new Uint8Array(view.buffer, view.byteOffset, view.byteLength));
      if (message.kind !== Kind.RESPONSE) return;
      const response = parseResponseBody(message.body);
      this.#settle(message.requestId, (pending) => pending.resolve(response));
    } catch (error) {
      if (!(error instanceof ProtocolError)) throw error;
      console.warn("Ignoring a bad packet from the computer:", error.message);
    }
  }

  #settle(requestId, action) {
    const pending = this.#pending.get(requestId);
    if (!pending) return; // a late answer to a request that already timed out
    clearTimeout(pending.timer);
    this.#pending.delete(requestId);
    action(pending);
  }

  #handleDisconnect() {
    for (const requestId of [...this.#pending.keys()]) {
      this.#settle(requestId, (pending) => pending.reject(new Error("Disconnected")));
    }
    this.onDisconnect();
  }
}
