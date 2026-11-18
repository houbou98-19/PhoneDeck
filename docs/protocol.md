# Protocol

How the phone and the computer talk. The layers, from the bottom:

```
Transport      packets (BLE writes and notifications)
Frame          | version 1 | kind 1 | length 2 | payload |
Message        | request id 2 | body |   (kind: COMMAND, QUERY, RESPONSE, HANDSHAKE)
SecureChannel  the body is encrypted and authenticated
Handler        the computer answers a request by name
```

All integers are big-endian. A frame is at most 512 bytes (the most a BLE write can hold), so
a message body is at most 506 bytes.

## BLE

The computer is the peripheral (GATT server), the phone is the central (Web Bluetooth).

- The **service UUID** is random per installation and kept in `~/.phonedeck/service_uuid`.
- The two characteristic UUIDs are derived from it: `uuid5(service_uuid, "write")` and
  `uuid5(service_uuid, "notify")`.
- The phone **writes** requests to the write characteristic. The computer **notifies**
  responses on the notify characteristic.

## Pairing

The computer makes a random 16-byte **pairing key** and shows it in a QR code. The code holds a
link, `https://<web page>/#<service uuid>.<key>`, with the key in URL-safe base64 without
padding. It sits after the `#`, so the browser never sends it to a server.

- The key is valid for 60 seconds and works once.
- The first failed attempt burns it: the computer makes a new one for the next try.
- The key never travels over Bluetooth.

## Handshake

Four HANDSHAKE messages, all with request id 0. The body is `| step 1 | data |`.

1. `CLIENT_HELLO` (1): the client's 16-byte nonce, in the clear
2. `SERVER_HELLO` (2): the server's 16-byte nonce, in the clear
3. `CLIENT_CONFIRM` (3): `seal(client_to_server, counter 0, aad, "")`
4. `SERVER_CONFIRM` (4): `seal(server_to_client, counter 0, aad, "")`

Both sides then derive two 32-byte session keys, one per direction:

```
HKDF-SHA256(ikm = pairing key, salt = client nonce + server nonce, info = "phonedeck v1 session")
  -> 64 bytes: client_to_server (first 32), server_to_client (last 32)
```

Step 3 proves to the server that the client has the pairing key, and step 4 proves it the other
way. Anything unexpected during the handshake closes the connection.

## Messages after the handshake

The body is `| counter 8 | AES-256-GCM ciphertext + tag 16 |`.

- The AES-GCM nonce is the counter as 12 bytes. Each direction has its own key and counts up
  from 1 (0 was used by the confirm).
- The associated data is `| kind 1 | request id 2 |`: visible, but a change to it is refused.
- The receiver requires a **strictly larger** counter than the last one, so a replay is refused.
- Anything that fails (a bad tag, a replay, a message in the clear, a HANDSHAKE message) closes
  the connection.

## Requests and responses

The body of a request is the UTF-8 name of an action. The response has the same request id, and
its body is `| status 1 | data |`.

| Status | Value |
|--------|-------|
| OK | 0 |
| UNKNOWN_ACTION | 1 |
| FAILED | 2 |

| Kind | Name | Data in the response |
|------|------|----------------------|
| QUERY | `cpu` | 1 byte, percent 0-100 |
| QUERY | `ram` | 1 byte, percent 0-100 |
| QUERY | `spotify` | 1 byte, 1 if Spotify runs |
| COMMAND | `lock` | none |
| COMMAND | `spotify` | none (starts Spotify) |
| COMMAND | `media_play_pause`, `media_next`, `media_previous` | none (Spotify only) |

The computer only runs names from this list. An unknown name, or a known name with the wrong
kind, gives UNKNOWN_ACTION and does nothing. If the computer cannot do it, the status is FAILED.
