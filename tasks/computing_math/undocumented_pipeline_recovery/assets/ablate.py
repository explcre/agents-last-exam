"""Ablate one decision at a time and measure what it costs.

Each ablation replaces a single decision in the reference with the obvious
alternative a competent engineer might write instead. Two things are measured at
once: whether the decision is WITNESSED (does it change any worked example, so it
can be inferred at all) and how much of the output it moves when got wrong.
"""
from __future__ import annotations

import csv
import pathlib
import subprocess

D = pathlib.Path("/tmp/galaxy_srv_disk00/pengchx3/etl")
REF = (D / "reference.sql").read_text()

ASOF_ORDER = ("ASOF JOIN fx_rates f\n  ON e.currency = f.currency "
              "AND CAST(e.placed_at AS DATE) >= f.day;")
PLAIN_ORDER = ("JOIN fx_rates f\n  ON e.currency = f.currency "
               "AND CAST(e.placed_at AS DATE) = f.day;")

ABLATIONS = {
    "keep every duplicate order row": ("WHERE rn = 1;", "WHERE rn >= 1;"),
    "dedup keeps the FIRST row": ("ORDER BY placed_at DESC, amount_cents ASC",
                                  "ORDER BY placed_at ASC, amount_cents ASC"),
    "count only 'paid', not 'settled'": ("status IN ('paid', 'settled')", "status IN ('paid')"),
    "plain FX join, no as-of (orders)": (ASOF_ORDER, PLAIN_ORDER),
    "credit note at the ORDER's day": (
        "ON e.currency = f.currency AND CAST(r.refunded_at AS DATE) >= f.day",
        "ON e.currency = f.currency AND CAST(e.placed_at AS DATE) >= f.day"),
    "no 30-day credit-note window": (
        "WHERE r.refunded_at < e.placed_at + INTERVAL 30 DAY\n", "\n"),
    "credit notes ignored entirely": (
        "greatest(o.usd_cents - coalesce(c.credit_usd, 0), 0) AS net_usd",
        "o.usd_cents AS net_usd"),
    "demand ordered by order_id only": (
        "PARTITION BY o.customer_id ORDER BY o.placed_at, o.order_id",
        "PARTITION BY o.customer_id ORDER BY o.order_id"),
    "supply ordered by payment_id only": (
        "PARTITION BY p.customer_id ORDER BY p.paid_at, p.payment_id",
        "PARTITION BY p.customer_id ORDER BY p.payment_id"),
    "cover test uses > not >=": ("s.cum_supply >= d.cum_demand", "s.cum_supply > d.cum_demand"),
    "recognise in the order's month": (
        "date_trunc('month', r.covered_at)", "date_trunc('month', r.placed_at)"),
    "recognise partially covered orders": (
        "WHERE r.covered_at IS NOT NULL\n    AND", "WHERE"),
    "drop unknown customers": (
        "LEFT JOIN customers c ON c.customer_id = r.customer_id",
        "JOIN customers c ON c.customer_id = r.customer_id"),
    "keep internal accounts": ("coalesce(c.tier, 'standard') <> 'internal'", "1=1"),
    "keep rows that net to zero": ("WHERE recognised_usd_cents > 0", "WHERE 1=1"),
}


def run(data, sql_text, tag):
    f = D / f"_ab_{tag}.sql"
    f.write_text(sql_text)
    out = D / f"_ab_{tag}.csv"
    subprocess.run([str(D / "run_case.sh"), str(data), str(f), str(out)],
                   check=True, capture_output=True)
    with out.open() as fh:
        return collections_counter(list(csv.reader(fh)))


def collections_counter(rows):
    import collections
    return collections.Counter(tuple(r) for r in rows)


def agree(a, b):
    hit = sum((a & b).values())
    tot = sum(a.values()) + sum(b.values())
    return 2 * hit / tot if tot else 1.0


def main():
    datasets = sorted((D / "cases").glob("ds_70*"))[:12]
    truth = {d: run(d, REF, "ref") for d in datasets}
    print(f"{'decision removed':<38}{'seen':>8}{'mean agr':>11}{'best':>8}")
    for i, (name, (a, b)) in enumerate(ABLATIONS.items()):
        if a not in REF:
            print(f"{name:<38}{'PATTERN NOT FOUND':>27}")
            continue
        scores = []
        for d in datasets:
            try:
                scores.append(agree(run(d, REF.replace(a, b), f"v{i}"), truth[d]))
            except subprocess.CalledProcessError:
                scores.append(0.0)          # an ablation that will not even run
        changed = sum(1 for s in scores if s < 0.9999)
        flag = "  INVISIBLE" if changed == 0 else ""
        print(f"{name:<38}{changed:>4}/{len(scores)}{sum(scores)/len(scores):>11.3f}"
              f"{max(scores):>8.3f}{flag}")


if __name__ == "__main__":
    main()
