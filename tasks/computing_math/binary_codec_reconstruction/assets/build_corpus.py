"""Generate documents and their encoded files with the reference codec."""
from __future__ import annotations

import json
import pathlib
import random
import sys

sys.path.insert(0, "/tmp/galaxy_srv_disk00/pengchx3/codec")
import reference_codec as R

WORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda", "mu", "sensor", "gateway", "ingest", "retry", "timeout", "packet", "queue", "flush", "commit"]


def make_doc(seed: int) -> dict:
    rng = random.Random(seed)
    recs, rid = [], rng.randint(1, 50)
    for _ in range(rng.randint(6, 22)):
        rid += rng.randint(1, 300)
        t = rng.choice([0, 0, 1, 2])
        v = (rng.randint(0, 10 ** 7) if t == 0 else
             round(rng.uniform(-1000, 1000), 5) if t == 1 else
             " ".join(rng.choices(WORDS, k=rng.randint(1, 8))))
        recs.append({"type": t, "id": rid, "name": rng.choice(WORDS),
                     "ts": rng.randint(1_600_000_000, 1_800_000_000), "value": v})
    # a payload with real repetition, so the compressor's policy actually matters
    phrases = [" ".join(rng.choices(WORDS, k=rng.randint(3, 7))) for _ in range(rng.randint(3, 8))]
    body = " ".join(rng.choices(phrases, k=rng.randint(20, 60)))
    return {"version": rng.choice([1, 2]), "records": recs, "payload": body}


def main():
    out = pathlib.Path(sys.argv[1])
    seeds = [int(x) for x in sys.argv[2:]]
    out.mkdir(parents=True, exist_ok=True)
    for s in seeds:
        doc = make_doc(s)
        blob = R.encode(doc)
        assert R.decode(blob)["payload"] == doc["payload"], f"seed {s} round trip"
        assert R.encode(R.decode(blob)) == blob, f"seed {s} re-encode"
        (out / f"sample_{s}.bin").write_bytes(blob)
        (out / f"sample_{s}.json").write_text(json.dumps(R.decode(blob), indent=1) + "\n")
    sizes = [len((out / f"sample_{s}.bin").read_bytes()) for s in seeds]
    print(f"{len(seeds)} samples, {min(sizes)}-{max(sizes)} bytes each")


if __name__ == "__main__":
    main()
