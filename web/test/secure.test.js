// Tests for secure.js (the phone's side of the handshake and the sealed messages).
//
// The hex strings are a whole conversation made by the Python code with fixed nonces
// (core/secure_channel.py). If the phone's side reproduces and accepts them byte for byte, the
// phone and the computer understand each other.

import assert from "node:assert/strict";
import test from "node:test";

import { MAX_BODY_SIZE, Kind } from "../protocol.js";
import { SEAL_OVERHEAD } from "../crypto.js";
import { ClientSession, SecureChannelError } from "../secure.js";

const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
const fromHex = (s) => Uint8Array.from(s.match(/../g) ?? [], (h) => parseInt(h, 16));
const range = (from, to) => Uint8Array.from({ length: to - from }, (_, i) => from + i);
const text = (s) => new TextEncoder().encode(s);

const PAIRING_KEY = range(0x00, 0x10);
const WRONG_KEY = range(0x40, 0x50);
const CLIENT_NONCE = range(0x10, 0x20);

// The conversation from Python.
const CLIENT_HELLO = "01040013000001101112131415161718191a1b1c1d1e1f";
const SERVER_HELLO = "01040013000002202122232425262728292a2b2c2d2e2f";
const CLIENT_CONFIRM = "0104001b000003000000000000000082365e20ab11f81bffb20454a915b983";
const SERVER_CONFIRM = "0104001b0000040000000000000000c62c06cf20226144649ab20a7aab5098";
const QUERY_CPU_ID2 = "0102001d000200000000000000010b46da2142140851efd91f418e66717d48cbc7";
const RESPONSE_ID2 = "0103001c00020000000000000001148543b23950ab19ab5b348189dc7354c400";
const RESPONSE_ID3 = "0103001c00030000000000000002b15e31a12f232eb84b9e34bd3b36fa870d26";

/** A session with the computer's fixed nonce, so that it makes the same bytes as Python. */
function newSession(key = PAIRING_KEY) {
  return new ClientSession(key, () => CLIENT_NONCE);
}

async function pairedSession() {
  const session = newSession();
  session.hello();
  await session.handleServerHello(fromHex(SERVER_HELLO));
  await session.handleServerConfirm(fromHex(SERVER_CONFIRM));
  return session;
}

// --- The handshake reproduces Python byte for byte ---

test("the hello is the known bytes", () => {
  assert.equal(hex(newSession().hello()), CLIENT_HELLO);
});

test("the answer to the computer's hello is the known confirm", async () => {
  const session = newSession();
  session.hello();

  const confirm = await session.handleServerHello(fromHex(SERVER_HELLO));

  assert.equal(hex(confirm), CLIENT_CONFIRM);
  assert.equal(session.ready, false); // the computer has not proved itself yet
});

test("the computer's known confirm is accepted, and the session is ready", async () => {
  const session = await pairedSession();

  assert.equal(session.ready, true);
});

test("a message to the computer is the known bytes", async () => {
  const session = await pairedSession();

  const packet = await session.seal(Kind.QUERY, 2, text("cpu"));

  assert.equal(hex(packet), QUERY_CPU_ID2);
});

test("the computer's known responses are read", async () => {
  const session = await pairedSession();

  const first = await session.open(fromHex(RESPONSE_ID2));
  assert.equal(first.kind, Kind.RESPONSE);
  assert.equal(first.requestId, 2);
  assert.deepEqual(Array.from(first.body), [0, 0x25]);

  const second = await session.open(fromHex(RESPONSE_ID3));
  assert.equal(second.requestId, 3);
  assert.deepEqual(Array.from(second.body), [0, 0x37]);
});

test("the counters of what the phone sends go up", async () => {
  const session = await pairedSession();

  const one = await session.seal(Kind.QUERY, 1, text("cpu"));
  const two = await session.seal(Kind.QUERY, 1, text("cpu"));

  assert.notEqual(hex(one), hex(two));
});

// --- A handshake that must fail ---

test("a computer that does not have the pairing key is not trusted", async () => {
  const session = newSession(WRONG_KEY); // the phone has another key than the computer
  session.hello();
  await session.handleServerHello(fromHex(SERVER_HELLO));

  await assert.rejects(session.handleServerConfirm(fromHex(SERVER_CONFIRM)), SecureChannelError);
  assert.equal(session.ready, false);
});

test("a hello with a nonce of the wrong size is refused", async () => {
  const session = newSession();
  session.hello();

  await assert.rejects(session.handleServerHello(fromHex("010400060000020102030405")), SecureChannelError);
});

test("the wrong handshake step is refused", async () => {
  const session = newSession();
  session.hello();

  // The computer's confirm, where its hello was expected.
  await assert.rejects(session.handleServerHello(fromHex(SERVER_CONFIRM)), SecureChannelError);
});

test("garbage during the handshake is refused", async () => {
  const session = newSession();
  session.hello();

  await assert.rejects(session.handleServerHello(fromHex("deadbeef")), SecureChannelError);
});

test("a confirm that was changed on the way is refused", async () => {
  const session = newSession();
  session.hello();
  await session.handleServerHello(fromHex(SERVER_HELLO));
  const changed = fromHex(SERVER_CONFIRM);
  changed[changed.length - 1] ^= 0x01;

  await assert.rejects(session.handleServerConfirm(changed), SecureChannelError);
});

// --- Misuse ---

test("nothing can be sent or read before the handshake", async () => {
  const session = newSession();

  await assert.rejects(session.seal(Kind.QUERY, 1, text("cpu")), SecureChannelError);
  await assert.rejects(session.open(fromHex(RESPONSE_ID2)), SecureChannelError);
});

test("a handshake message cannot be sent as data, and a too large body is refused", async () => {
  const session = await pairedSession();

  await assert.rejects(session.seal(Kind.HANDSHAKE, 0, text("x")), SecureChannelError);
  await assert.rejects(
    session.seal(Kind.RESPONSE, 1, new Uint8Array(MAX_BODY_SIZE - SEAL_OVERHEAD + 1)),
    SecureChannelError,
  );
  // The largest body that fits is fine.
  const packet = await session.seal(Kind.RESPONSE, 1, new Uint8Array(MAX_BODY_SIZE - SEAL_OVERHEAD));
  assert.equal(packet.length, 512);
});

// --- An attacker after the handshake: everything is refused ---

test("a changed message from the computer is refused", async () => {
  const session = await pairedSession();
  const changed = fromHex(RESPONSE_ID2);
  changed[changed.length - 1] ^= 0x01;

  await assert.rejects(session.open(changed), SecureChannelError);
});

test("a changed request id or kind is refused", async () => {
  const session = await pairedSession();
  const otherId = fromHex(RESPONSE_ID2);
  otherId[5] ^= 0x01; // request id 2 becomes 3
  const otherKind = fromHex(RESPONSE_ID2);
  otherKind[1] = Kind.QUERY; // a RESPONSE dressed up as a QUERY

  await assert.rejects(session.open(otherId), SecureChannelError);
  await assert.rejects(session.open(otherKind), SecureChannelError);
});

test("a repeated or an old message is refused", async () => {
  const session = await pairedSession();
  await session.open(fromHex(RESPONSE_ID2)); // counter 1
  await session.open(fromHex(RESPONSE_ID3)); // counter 2

  await assert.rejects(session.open(fromHex(RESPONSE_ID3)), SecureChannelError); // again
  await assert.rejects(session.open(fromHex(RESPONSE_ID2)), SecureChannelError); // older
});

test("a message in the clear after the handshake is refused", async () => {
  const session = await pairedSession();

  // A plain RESPONSE (request id 1, status OK) that nobody sealed.
  await assert.rejects(session.open(fromHex("01030003000100")), SecureChannelError);
});

test("a handshake message after the handshake is refused", async () => {
  const session = await pairedSession();

  await assert.rejects(session.open(fromHex(SERVER_HELLO)), SecureChannelError);
});
