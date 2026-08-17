"""How far does one wrong decision propagate through an encoded file?

A local error leaves most bytes intact and the agent can localise it. An entangled
error moves everything after it, which is what removes the gradient. This measures
the fraction of bytes that change when a single encoder decision is altered.
"""
from __future__ import annotations

import importlib
import random
import struct
import sys

sys.path.insert(0, "/tmp/galaxy_srv_disk00/pengchx3/codec")
import reference_codec as R

WORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]


def make_doc(seed):
    rng = random.Random(seed)
    n = rng.randint(8, 20)
    recs, rid = [], rng.randint(1, 50)
    for _ in range(n):
        rid += rng.randint(1, 40)
        t = rng.choice([0, 0, 1, 2])
        v = (rng.randint(0, 10**6) if t == 0 else
             round(rng.uniform(-500, 500), 4) if t == 1 else
             " ".join(rng.choices(WORDS, k=rng.randint(1, 6))))
        recs.append({"type": t, "id": rid, "name": rng.choice(WORDS),
                     "ts": rng.randint(1_600_000_000, 1_800_000_000), "value": v})
    body = " ".join(rng.choices(WORDS, k=rng.randint(60, 200)))
    return {"version": rng.choice([1, 2]), "records": recs, "payload": body}


def diff_fraction(a: bytes, b: bytes) -> float:
    n = max(len(a), len(b))
    if n == 0:
        return 0.0
    same = sum(1 for x, y in zip(a, b) if x == y)
    return 1.0 - same / n


def first_divergence(a: bytes, b: bytes) -> int:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def with_patch(name):
    """Re-import the reference with one decision altered."""
    importlib.reload(R)
    if name == "lz77 prefers the most recent match":
        def comp(data):
            out, i = bytearray(), 0
            while i < len(data):
                best_len, best_off = 0, 0
                for j in range(max(0, i - 4096), i):
                    k = 0
                    while (i + k < len(data) and data[j + k] == data[i + k]
                           and k < 255 and j + k < i):
                        k += 1
                    if k >= best_len:                 # >= keeps the latest instead
                        best_len, best_off = k, i - j
                if best_len >= 4:
                    out.append(0x01); out += R.put_varint(best_off) + R.put_varint(best_len)
                    i += best_len
                else:
                    run = data[i:i + 127]
                    out.append(0x00); out += R.put_varint(len(run)) + run
                    i += len(run)
            return bytes(out)
        R.lz77_compress = comp
    elif name == "string table sorted, not first-use":
        orig = R.encode
        def enc(doc):
            d = dict(doc)
            names = sorted({r["name"] for r in d["records"]})
            order = {n: k for k, n in enumerate(names)}
            d["records"] = sorted(d["records"], key=lambda r: (order[r["name"]],))
            return orig(d)
        R.encode = enc
    elif name == "checksum uses the standard init":
        R.INIT = 0xFFFF
    elif name == "no four-byte padding":
        orig = R.encode
        def enc(doc):
            b = bytearray(orig(doc))
            return bytes(b)
        R.encode = enc
    elif name == "minimum match length 3":
        def comp(data):
            out, i = bytearray(), 0
            while i < len(data):
                best_len, best_off = 0, 0
                for j in range(max(0, i - 4096), i):
                    k = 0
                    while (i + k < len(data) and data[j + k] == data[i + k]
                           and k < 255 and j + k < i):
                        k += 1
                    if k > best_len:
                        best_len, best_off = k, i - j
                if best_len >= 3:
                    out.append(0x01); out += R.put_varint(best_off) + R.put_varint(best_len)
                    i += best_len
                else:
                    run = data[i:i + 127]
                    out.append(0x00); out += R.put_varint(len(run)) + run
                    i += len(run)
            return bytes(out)
        R.lz77_compress = comp
    return R


def main():
    docs = [make_doc(s) for s in range(20)]
    importlib.reload(R)
    truth = [R.encode(d) for d in docs]
    print(f"{'decision changed':<38}{'bytes differ':>13}{'first diff at':>15}")
    for name in ["lz77 prefers the most recent match", "string table sorted, not first-use",
                 "checksum uses the standard init", "minimum match length 3"]:
        mod = with_patch(name)
        fr, pos = [], []
        for d, t in zip(docs, truth):
            try:
                got = mod.encode(d)
            except (AssertionError, ValueError, IndexError, struct.error):
                fr.append(1.0); pos.append(0); continue
            fr.append(diff_fraction(got, t))
            pos.append(first_divergence(got, t) / max(1, len(t)))
        print(f"{name:<38}{sum(fr)/len(fr):>12.1%}{sum(pos)/len(pos):>14.1%}")
        importlib.reload(R)


if __name__ == "__main__":
    main()
