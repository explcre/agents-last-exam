"""Reference codec for the TLG1 container. Never shipped to the agent.

The format is deliberately entangled: several fields depend on decisions made
earlier in the same stream, so an error does not stay where it was made.

  * record ids are delta-encoded, so one wrong delta shifts every later id
  * the string table is ordered by first use, so emitting a name early changes
    every later reference index
  * the payload is LZ77-compressed with a specific match policy, so choosing a
    different match changes every subsequent offset
  * a checksum covers the exact bytes, so any of the above is fatal to the whole file
  * the body is padded to a four-byte boundary before the payload

Decoding is forgiving of none of this; encoding byte-exactly requires all of it.
"""
from __future__ import annotations

import struct

MAGIC = b"TLG1"
POLY = 0x1021          # CRC-16/CCITT polynomial, non-standard init below
INIT = 0x3B9A


def crc16(data: bytes) -> int:
    crc = INIT
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ POLY) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def put_varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("varint is unsigned")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def get_varint(buf: bytes, i: int) -> tuple[int, int]:
    n, shift = 0, 0
    while True:
        b = buf[i]; i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


WINDOW, MIN_MATCH, MAX_MATCH, LAZY_GAIN = 4096, 4, 255, 2


def _best_match(data: bytes, i: int) -> tuple[int, int]:
    """Longest match in the window; the earliest position wins a tie."""
    best_len, best_off = 0, 0
    for j in range(max(0, i - WINDOW), i):
        k = 0
        while (i + k < len(data) and data[j + k] == data[i + k]
               and k < MAX_MATCH and j + k < i):
            k += 1
        if k > best_len:                          # strictly greater keeps the earliest
            best_len, best_off = k, i - j
    return best_len, best_off


def lz77_compress(data: bytes) -> bytes:
    """Lazy matching over a 4096 window, minimum match 4, earliest position on a tie.

    Lazy matching is what makes a compressor hard to reproduce byte for byte. At each
    position the encoder also looks at the next one, and defers the current match if
    the next is longer by more than LAZY_GAIN, emitting a literal instead. Deferring
    or not changes the offset of everything that follows.
    """
    out, i = bytearray(), 0
    literals = bytearray()

    def emit_literals():
        nonlocal literals
        while literals:
            chunk = bytes(literals[:127])
            out.append(0x00)
            out.extend(put_varint(len(chunk)))
            out.extend(chunk)
            del literals[:len(chunk)]

    while i < len(data):
        blen, boff = _best_match(data, i)
        if blen >= MIN_MATCH:
            nlen, _ = _best_match(data, i + 1) if i + 1 < len(data) else (0, 0)
            if nlen > blen + LAZY_GAIN:           # defer: the next match is worth more
                literals.append(data[i]); i += 1
                continue
            emit_literals()
            out.append(0x01)
            out.extend(put_varint(boff)); out.extend(put_varint(blen))
            i += blen
        else:
            literals.append(data[i]); i += 1
    emit_literals()
    return bytes(out)


def lz77_decompress(buf: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(buf):
        tag = buf[i]; i += 1
        if tag == 0x01:
            off, i = get_varint(buf, i)
            ln, i = get_varint(buf, i)
            for _ in range(ln):
                out.append(out[len(out) - off])
        else:
            ln, i = get_varint(buf, i)
            out += buf[i:i + ln]; i += ln
    return bytes(out)


def encode(doc: dict) -> bytes:
    records = doc["records"]
    # string table in order of first use, deduplicated
    table, index = [], {}
    for r in records:
        if r["name"] not in index:
            index[r["name"]] = len(table)
            table.append(r["name"])

    body = bytearray()
    body += put_varint(len(table))
    for s in table:
        raw = s.encode("utf-8")
        body += put_varint(len(raw)) + raw
    body += put_varint(len(records))

    prev_id = 0
    for r in records:
        body.append(r["type"])
        body += put_varint(r["id"] - prev_id)          # delta from the previous id
        prev_id = r["id"]
        body += put_varint(index[r["name"]])
        body += struct.pack("<I", r["ts"])
        if r["type"] == 0:
            body += put_varint(r["value"])
        elif r["type"] == 1:
            body += struct.pack("<d", r["value"])
        else:
            raw = r["value"].encode("utf-8")
            body += put_varint(len(raw)) + raw

    head = bytearray(MAGIC)
    head.append(doc["version"])
    head.append(0x03)                                   # table present, payload compressed
    out = bytearray(head + body)
    out += struct.pack("<H", crc16(bytes(out)))         # checksum covers header and body
    while len(out) % 4:                                 # pad to a four-byte boundary
        out.append(0x00)
    payload = doc["payload"].encode("utf-8")
    comp = lz77_compress(payload)
    out += put_varint(len(payload)) + put_varint(len(comp)) + comp
    return bytes(out)


def decode(buf: bytes) -> dict:
    assert buf[:4] == MAGIC, "bad magic"
    version, flags = buf[4], buf[5]
    i = 6
    n_str, i = get_varint(buf, i)
    table = []
    for _ in range(n_str):
        ln, i = get_varint(buf, i)
        table.append(buf[i:i + ln].decode("utf-8")); i += ln
    n_rec, i = get_varint(buf, i)
    records, prev_id = [], 0
    for _ in range(n_rec):
        t = buf[i]; i += 1
        d, i = get_varint(buf, i)
        rid = prev_id + d; prev_id = rid
        ref, i = get_varint(buf, i)
        ts = struct.unpack_from("<I", buf, i)[0]; i += 4
        if t == 0:
            v, i = get_varint(buf, i)
        elif t == 1:
            v = struct.unpack_from("<d", buf, i)[0]; i += 8
        else:
            ln, i = get_varint(buf, i)
            v = buf[i:i + ln].decode("utf-8"); i += ln
        records.append({"type": t, "id": rid, "name": table[ref], "ts": ts, "value": v})
    stored = struct.unpack_from("<H", buf, i)[0]
    assert crc16(buf[:i]) == stored, "checksum mismatch"
    i += 2
    while i % 4:
        i += 1
    raw_len, i = get_varint(buf, i)
    comp_len, i = get_varint(buf, i)
    payload = lz77_decompress(buf[i:i + comp_len])
    assert len(payload) == raw_len, "payload length mismatch"
    return {"version": version, "flags": flags, "records": records,
            "payload": payload.decode("utf-8")}
