"""Score a reconstructed codec against the reference container format.

Two halves with very different difficulty. Decoding a file is checkable against the
worked samples and is expected to be reachable; re-encoding a document to the exact
bytes the reference produced is not, because several of the encoder's decisions
propagate through the whole stream. Encoding therefore carries most of the score and
decoding supplies the partial credit that shows progress.

Standard library only. No path raises on a missing or malformed result.
"""

from __future__ import annotations

ENCODE_WEIGHT = 0.75


def _norm(value):
    """Compare decoded documents structurally, tolerating int/float spelling."""
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 9)
    return value


def score(results: dict, expected: dict) -> dict:
    """``results`` maps sample name to {"decoded": obj|None, "encoded_hex": str|None}."""
    names = sorted(expected)
    dec_ok = enc_ok = 0
    per_sample = {}
    for name in names:
        want_doc = expected[name]["doc"]
        want_hex = expected[name]["hex"]
        got = results.get(name) if isinstance(results, dict) else None
        got = got if isinstance(got, dict) else {}
        d = got.get("decoded")
        decoded_ok = d is not None and _norm(d) == _norm(want_doc)
        h = got.get("encoded_hex")
        encoded_ok = isinstance(h, str) and h.strip().lower() == want_hex.strip().lower()
        dec_ok += decoded_ok
        enc_ok += encoded_ok
        per_sample[name] = {"decoded": decoded_ok, "encoded": encoded_ok}
    n = len(names)
    d_frac = dec_ok / n if n else 0.0
    e_frac = enc_ok / n if n else 0.0
    return {"samples": n, "decoded": dec_ok, "encoded": enc_ok,
            "decode_fraction": d_frac, "encode_fraction": e_frac,
            "per_sample": per_sample,
            "reward": max(0.0, ENCODE_WEIGHT * e_frac + (1 - ENCODE_WEIGHT) * d_frac)}
