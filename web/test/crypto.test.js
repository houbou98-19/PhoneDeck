// Tests for crypto.js. The known values were made by the Python code (security/crypto.py) with the
// `cryptography` library, so Python is the reference: if these pass, the phone and the computer
// derive the same keys and understand each other's sealed messages.

import assert from "node:assert/strict";
import test from "node:test";

import {
  COUNTER_SIZE,
  CryptoError,
  KEY_SIZE,
  MAX_COUNTER,
  NONCE_SIZE,
  SEAL_OVERHEAD,
  deriveSessionKeys,
  newNonce,
  openSealed,
  seal,
} from "../crypto.js";

const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
const fromHex = (s) => Uint8Array.from(s.match(/../g) ?? [], (h) => parseInt(h, 16));
const range = (from, to) => Uint8Array.from({ length: to - from }, (_, i) => from + i);
const text = (s) => new TextEncoder().encode(s);

const PAIRING_KEY = range(0x00, 0x10);
const CLIENT_NONCE = range(0x10, 0x20);
const SERVER_NONCE = range(0x20, 0x30);

async function keys() {
  return deriveSessionKeys(PAIRING_KEY, CLIENT_NONCE, SERVER_NONCE);
}

// --- Random values ---

test("a nonce has the right size and is random", () => {
  assert.equal(newNonce().length, NONCE_SIZE);
  assert.notEqual(hex(newNonce()), hex(newNonce()));
});

// --- Key derivation (the keys are not readable, so they are checked through sealing) ---

test("the derived keys seal to the known values", async () => {
  const { clientToServer, serverToClient } = await keys();

  // The client-to-server key: counter 1, aad 02 00 07, plaintext "cpu".
  const sealed = await seal(clientToServer, 1, Uint8Array.of(2, 0, 7), text("cpu"));
  assert.equal(hex(sealed), "00000000000000010b46daaa836606dc0565fe3c401b6f745a45fe");

  // The server-to-client key: counter 0, nothing to seal, no aad.
  const empty = await seal(serverToClient, 0, new Uint8Array(), new Uint8Array());
  assert.equal(hex(empty), "0000000000000000bf30808957a8accfdc104103239b8b99");
});

test("deriveSessionKeys rejects the wrong sizes", async () => {
  await assert.rejects(deriveSessionKeys(new Uint8Array(5), CLIENT_NONCE, SERVER_NONCE), CryptoError);
  await assert.rejects(deriveSessionKeys(PAIRING_KEY, new Uint8Array(5), SERVER_NONCE), CryptoError);
  await assert.rejects(deriveSessionKeys(PAIRING_KEY, CLIENT_NONCE, new Uint8Array(17)), CryptoError);
});

test("another nonce gives other keys", async () => {
  const one = await keys();
  const other = await deriveSessionKeys(PAIRING_KEY, newNonce(), SERVER_NONCE);

  const a = await seal(one.clientToServer, 1, new Uint8Array(), text("x"));
  const b = await seal(other.clientToServer, 1, new Uint8Array(), text("x"));
  assert.notEqual(hex(a), hex(b));
});

// --- Sealing and opening ---

test("a sealed message is longer by the counter and the tag, and the counter is in the clear", async () => {
  const { clientToServer } = await keys();
  const sealed = await seal(clientToServer, 258, new Uint8Array(), text("hello"));

  assert.equal(sealed.length, 5 + SEAL_OVERHEAD);
  assert.equal(SEAL_OVERHEAD, COUNTER_SIZE + 16);
  assert.equal(hex(sealed.slice(0, COUNTER_SIZE)), "0000000000000102");
});

test("openSealed returns the counter and the plaintext", async () => {
  const { clientToServer } = await keys();
  const sealed = await seal(clientToServer, 42, text("aad"), text("lock"));

  const opened = await openSealed(clientToServer, text("aad"), sealed);

  assert.equal(opened.counter, 42);
  assert.equal(new TextDecoder().decode(opened.plaintext), "lock");
});

test("openSealed reads the known value from Python", async () => {
  const { clientToServer } = await keys();
  const sealed = fromHex("00000000000000010b46daaa836606dc0565fe3c401b6f745a45fe");

  const opened = await openSealed(clientToServer, Uint8Array.of(2, 0, 7), sealed);

  assert.equal(opened.counter, 1);
  assert.equal(new TextDecoder().decode(opened.plaintext), "cpu");
});

test("the largest counter that JavaScript can count exactly works", async () => {
  const { clientToServer } = await keys();
  const sealed = await seal(clientToServer, MAX_COUNTER, new Uint8Array(), text("x"));

  assert.equal((await openSealed(clientToServer, new Uint8Array(), sealed)).counter, MAX_COUNTER);
});

// --- Anything tampered with is refused ---

test("a changed byte, a changed tag or a changed counter is refused", async () => {
  const { clientToServer } = await keys();
  const sealed = await seal(clientToServer, 1, new Uint8Array(), text("hello"));

  for (const index of [COUNTER_SIZE, sealed.length - 1, COUNTER_SIZE - 1]) {
    const changed = sealed.slice();
    changed[index] ^= 0x01;
    await assert.rejects(openSealed(clientToServer, new Uint8Array(), changed), CryptoError);
  }
});

test("the wrong aad or the wrong key is refused", async () => {
  const { clientToServer, serverToClient } = await keys();
  const sealed = await seal(clientToServer, 1, Uint8Array.of(2, 0, 7), text("cpu"));

  await assert.rejects(openSealed(clientToServer, Uint8Array.of(2, 0, 8), sealed), CryptoError);
  await assert.rejects(openSealed(serverToClient, Uint8Array.of(2, 0, 7), sealed), CryptoError);
});

test("a message that is too short is refused", async () => {
  const { clientToServer } = await keys();

  for (const length of [0, 1, SEAL_OVERHEAD - 1]) {
    await assert.rejects(openSealed(clientToServer, new Uint8Array(), new Uint8Array(length)), CryptoError);
  }
});

test("a counter out of range is refused", async () => {
  const { clientToServer } = await keys();

  for (const bad of [-1, MAX_COUNTER + 1, 1.5, "1", NaN]) {
    await assert.rejects(seal(clientToServer, bad, new Uint8Array(), text("x")), CryptoError);
  }
});

test("the key sizes are the agreed ones", () => {
  assert.equal(KEY_SIZE, 32);
});
