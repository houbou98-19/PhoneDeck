// Tests for protocol.js. Run them with:  node --test web/test/   (or: cd web; npm test)
//
// The known values are the same as in the Python tests, so Python is the reference.

import assert from "node:assert/strict";
import test from "node:test";

import {
  HEADER_SIZE,
  Kind,
  MAX_BODY_SIZE,
  MAX_PAYLOAD_SIZE,
  ProtocolError,
  Status,
  characteristicUuids,
  decodeMessage,
  encodeMessage,
  parseResponseBody,
  uuid5,
} from "../protocol.js";

const SERVICE_A = "7d2a0001-8c1e-4b6f-9a3d-5e1f0c2b4a10";
const SERVICE_B = "11111111-2222-4333-8444-555555555555";

const text = (s) => new TextEncoder().encode(s);
const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
const fromHex = (s) => Uint8Array.from(s.match(/../g) ?? [], (h) => parseInt(h, 16));

// --- UUIDs (the values come from Python's uuid.uuid5) ---

test("uuid5 gives the same values as Python", async () => {
  assert.equal(await uuid5(SERVICE_A, "write"), "716749bc-88a2-58d3-a999-fb7483ff6ff3");
  assert.equal(await uuid5(SERVICE_A, "notify"), "37831094-ceff-5940-bdc6-b04c098bf841");
  assert.equal(await uuid5(SERVICE_B, "write"), "ce82801f-da76-579c-bf27-d2bc78fa0c6b");
  assert.equal(await uuid5(SERVICE_B, "notify"), "f106132c-6a0b-5dad-9153-a6da4406c37f");
});

test("uuid5 treats capital letters in the namespace like lowercase", async () => {
  assert.equal(await uuid5(SERVICE_A.toUpperCase(), "write"), await uuid5(SERVICE_A, "write"));
});

test("uuid5 rejects a namespace that is not a UUID", async () => {
  for (const bad of ["", "not a uuid", "7d2a0001"]) {
    await assert.rejects(uuid5(bad, "write"), ProtocolError);
  }
});

test("characteristicUuids gives the write and notify UUIDs of a service", async () => {
  assert.deepEqual(await characteristicUuids(SERVICE_A), {
    write: "716749bc-88a2-58d3-a999-fb7483ff6ff3",
    notify: "37831094-ceff-5940-bdc6-b04c098bf841",
  });
  assert.deepEqual(await characteristicUuids(SERVICE_B), {
    write: "ce82801f-da76-579c-bf27-d2bc78fa0c6b",
    notify: "f106132c-6a0b-5dad-9153-a6da4406c37f",
  });
});

test("characteristicUuids rejects a service that is not a UUID", async () => {
  await assert.rejects(characteristicUuids("nope"), ProtocolError);
});

// --- Encoding (the hex strings are the ones the phone sent in nRF Connect) ---

test("encodeMessage gives the known bytes", () => {
  assert.equal(hex(encodeMessage(Kind.COMMAND, 1, text("lock"))), "0101000600016c6f636b");
  assert.equal(hex(encodeMessage(Kind.QUERY, 2, text("cpu"))), "010200050002637075");
  assert.equal(hex(encodeMessage(Kind.QUERY, 3, text("ram"))), "01020005000372616d");
  assert.equal(hex(encodeMessage(Kind.RESPONSE, 1, Uint8Array.of(0))), "01030003000100");
});

test("encodeMessage writes numbers big-endian", () => {
  // 513 is 0x0201, so the high byte 02 comes first. The length (0002) is the request id alone.
  assert.equal(hex(encodeMessage(Kind.QUERY, 513, new Uint8Array())), "010200020201");
  assert.equal(hex(encodeMessage(Kind.QUERY, 65535, new Uint8Array())), "01020002ffff");
});

test("encodeMessage accepts the largest body and the result fits in one BLE write", () => {
  const packet = encodeMessage(Kind.RESPONSE, 65535, new Uint8Array(MAX_BODY_SIZE));
  assert.equal(packet.length, HEADER_SIZE + MAX_PAYLOAD_SIZE);
  assert.equal(packet.length, 512);
});

test("encodeMessage rejects a body that is too large", () => {
  assert.throws(() => encodeMessage(Kind.COMMAND, 1, new Uint8Array(MAX_BODY_SIZE + 1)), ProtocolError);
});

test("encodeMessage rejects a bad request id", () => {
  for (const bad of [-1, 65536, 1.5, "1", NaN]) {
    assert.throws(() => encodeMessage(Kind.COMMAND, bad, new Uint8Array()), ProtocolError);
  }
});

test("encodeMessage rejects an unknown kind", () => {
  for (const bad of [0, 5, 99, "1"]) {
    assert.throws(() => encodeMessage(bad, 1, new Uint8Array()), ProtocolError);
  }
});

// --- Decoding ---

test("decodeMessage reads the known responses", () => {
  const ok = decodeMessage(fromHex("01030003000100"));
  assert.equal(ok.kind, Kind.RESPONSE);
  assert.equal(ok.requestId, 1);
  assert.deepEqual(Array.from(ok.body), [0]);

  const cpu = decodeMessage(fromHex("0103000400020025"));
  assert.equal(cpu.requestId, 2);
  assert.deepEqual(Array.from(cpu.body), [0, 37]);
});

test("a message survives encode then decode", () => {
  const packet = encodeMessage(Kind.QUERY, 513, text("ram"));
  const message = decodeMessage(packet);
  assert.equal(message.kind, Kind.QUERY);
  assert.equal(message.requestId, 513);
  assert.equal(new TextDecoder().decode(message.body), "ram");
});

test("decodeMessage rejects a packet that is too short", () => {
  for (const bad of ["", "01", "010300"]) {
    assert.throws(() => decodeMessage(fromHex(bad)), ProtocolError);
  }
});

test("decodeMessage rejects the wrong version", () => {
  assert.throws(() => decodeMessage(fromHex("02030003000100")), ProtocolError);
});

test("decodeMessage rejects a length that does not match the bytes", () => {
  assert.throws(() => decodeMessage(fromHex("010300040001")), ProtocolError); // too few bytes
  assert.throws(() => decodeMessage(fromHex("0103000300010000")), ProtocolError); // too many
});

test("decodeMessage rejects a payload too short to hold a request id", () => {
  assert.throws(() => decodeMessage(fromHex("0103000100")), ProtocolError);
});

test("decodeMessage rejects an unknown kind", () => {
  assert.throws(() => decodeMessage(fromHex("01630003000100")), ProtocolError);
});

// --- Response bodies ---

test("parseResponseBody splits the status from the data", () => {
  const { status, data } = parseResponseBody(Uint8Array.of(0, 37));
  assert.equal(status, Status.OK);
  assert.deepEqual(Array.from(data), [37]);

  const refused = parseResponseBody(Uint8Array.of(1));
  assert.equal(refused.status, Status.UNKNOWN_ACTION);
  assert.equal(refused.data.length, 0);
});

test("parseResponseBody rejects an empty body", () => {
  assert.throws(() => parseResponseBody(new Uint8Array()), ProtocolError);
});
