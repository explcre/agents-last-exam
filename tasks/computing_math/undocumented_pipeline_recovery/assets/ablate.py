"""Ablate one decision at a time and measure what it costs.

Each ablation is the reference with a single subtlety replaced by the obvious
alternative a competent engineer might write instead. Two things are being measured
at once: whether the decision is WITNESSED (does it change the output at all, so it
can be inferred from examples) and whether it MATTERS (how much of the output moves).
"""
from __future__ import annotations

import csv
import pathlib
import subprocess

D = pathlib.Path("/tmp/galaxy_srv_disk00/pengchx3/etl")
REF = (D / "reference.sql").read_text()

ABLATIONS = {
    "keep every duplicate order row": (
        "WHERE rn = 1;", "WHERE rn >= 1;"),
    "dedup keeps the FIRST row, not the last": (
        "ORDER BY placed_at DESC, amount_cents ASC", "ORDER BY placed_at ASC, amount_cents ASC"),
    "count only 'paid', not 'settled'": (
        "status IN ('paid', 'settled')", "status IN ('paid')"),
    "allow non-positive amounts": (
        "AND amount_cents > 0", "AND amount_cents <> 0"),
    "plain join on the day, no as-of": (
        "ASOF JOIN fx_rates f\n  ON e.currency = f.currency AND CAST(e.placed_at AS DATE) >= f.day;",
        "JOIN fx_rates f\n  ON e.currency = f.currency AND CAST(e.placed_at AS DATE) = f.day;"),
    "refund converted at the ORDER's day": (
        "ON e.currency = f.currency AND CAST(r.refunded_at AS DATE) >= f.day",
        "ON e.currency = f.currency AND CAST(e.placed_at AS DATE) >= f.day"),
    "no 30-day refund window": (
        "WHERE r.refunded_at < e.placed_at + INTERVAL 30 DAY;", ";"),
    "drop unknown customers instead of UNKNOWN": (
        "LEFT JOIN customers c ON c.customer_id = o.customer_id",
        "JOIN customers c ON c.customer_id = o.customer_id"),
    "keep internal accounts": (
        "WHERE coalesce(c.tier, 'standard') <> 'internal'", "WHERE 1=1"),
    "keep months that net to zero or below": (
        "WHERE net_usd_cents > 0", "WHERE 1=1"),
}


def run(data, sql_text, tag):
    f = D / f"_ab_{tag}.sql"; f.write_text(sql_text)
    out = D / f"_ab_{tag}.csv"
    subprocess.run([str(D / "run_case.sh"), str(data), str(f), str(out)],
                   check=True, capture_output=True)
    with out.open() as fh:
        return {tuple(row) for row in csv.reader(fh)}


def main():
    datasets = sorted((D / "cases").glob("ds_70*"))[:12]
    truth = {d: run(d, REF, "ref") for d in datasets}
    print(f"{'decision removed':<44}{'seen':>7}{'mean agr':>11}{'best':>9}")
    for i, (name, (a, b)) in enumerate(ABLATIONS.items()):
        if a not in REF:
            print(f"{name:<44}{'PATTERN NOT FOUND':>18}"); continue
        agree = []
        for d in datasets:
            got = run(d, REF.replace(a, b), f"v{i}")
            t = truth[d]
            inter = len(got & t)
            agree.append(2 * inter / (len(got) + len(t)) if (got or t) else 1.0)
        m = sum(agree) / len(agree)
        worst = max(agree)
        changed = sum(1 for a_ in agree if a_ < 0.9999)
        flag = "  INVISIBLE" if changed == 0 else ""
        print(f"{name:<44}{changed:>4}/{len(agree)}{m:>11.3f}{worst:>9.3f}{flag}")


if __name__ == "__main__":
    main()
