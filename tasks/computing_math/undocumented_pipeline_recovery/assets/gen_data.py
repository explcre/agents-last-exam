"""Generate one synthetic billing dataset per seed, deterministically.

Four input tables in the shape a real revenue pipeline sees: orders, customers,
refunds and daily FX rates. The data deliberately contains the situations that make
such a pipeline subtle, and the generator guarantees each appears often enough to be
inferable: duplicated order ids, refunds straddling the eligibility window, orders in
currencies whose rate is missing on the order's own day, unknown customers, internal
accounts, and months that net out to zero or below.
"""
from __future__ import annotations

import csv
import datetime as dt
import pathlib
import sys

CURRENCIES = ["USD", "EUR", "GBP", "JPY"]
REGIONS = ["NA", "EMEA", "APAC"]
TIERS = ["standard", "plus", "internal"]
STATUSES = ["paid", "settled", "pending", "void"]
DAY0 = dt.date(2024, 1, 1)
# Naive wall clock on purpose: the source system records local timestamps
# without a zone, which is part of what the pipeline has to cope with.
T0 = dt.datetime(2024, 1, 1)  # noqa: DTZ001


class R:
    """xorshift32, so a dataset is a pure function of its seed."""
    def __init__(self, seed): self.s = seed & 0xFFFFFFFF or 1
    def next(self):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF; s ^= s >> 17; s ^= (s << 5) & 0xFFFFFFFF
        self.s = s & 0xFFFFFFFF
        return self.s
    def i(self, n): return self.next() % n
    def pick(self, xs): return xs[self.i(len(xs))]


def build(seed: int, out: pathlib.Path):
    r = R(seed)
    out.mkdir(parents=True, exist_ok=True)

    n_cust = 18 + r.i(10)
    customers = []
    for c in range(1, n_cust + 1):
        tier = "internal" if r.i(9) == 0 else r.pick(TIERS[:2])
        customers.append({
            "customer_id": c,
            "region": r.pick(REGIONS),
            "tier": tier,
            "signed_up_at": (DAY0 + dt.timedelta(days=r.i(120))).isoformat(),
        })

    # FX: a rate for most days, with deliberate gaps so an as-of lookup is needed
    fx = []
    for cur in CURRENCIES:
        base = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067}[cur]
        for d in range(190):
            if cur != "USD" and (d % 7 in (5, 6)):      # no weekend rates
                continue
            drift = ((r.i(2001) - 1000) / 100000.0)
            fx.append({"currency": cur, "day": (DAY0 + dt.timedelta(days=d)).isoformat(),
                       "rate_to_usd": round(base * (1 + drift), 6)})

    n_orders = 120 + r.i(80)
    orders, next_id = [], 1000
    for _ in range(n_orders):
        oid = next_id; next_id += 1
        cid = 1 + r.i(n_cust + 3)          # a few ids past the end: unknown customers
        placed = T0 + dt.timedelta(days=r.i(180), hours=r.i(24), minutes=r.i(60))
        row = {
            "order_id": oid,
            "customer_id": cid,
            "placed_at": placed.replace(microsecond=0).isoformat(sep=" "),
            "amount_cents": (50 + r.i(90000)) * (1 if r.i(20) else -1),
            "currency": r.pick(CURRENCIES),
            "status": r.pick(STATUSES) if r.i(4) else "paid",
        }
        orders.append(row)
        if r.i(11) == 0:                    # a duplicated order id, later and cheaper
            dup = dict(row)
            dup["placed_at"] = (placed + dt.timedelta(hours=1 + r.i(48))).replace(microsecond=0).isoformat(sep=" ")
            dup["amount_cents"] = max(50, row["amount_cents"] - (1 + r.i(500)))
            orders.append(dup)

    refunds, rid = [], 5000
    for o in orders:
        if r.i(5):
            continue
        placed = dt.datetime.fromisoformat(o["placed_at"])
        # straddle the 30-day eligibility window on purpose
        delay = r.i(46)
        refunds.append({
            "refund_id": rid,
            "order_id": o["order_id"],
            "refunded_at": (placed + dt.timedelta(days=delay, hours=r.i(24))).replace(microsecond=0).isoformat(sep=" "),
            "amount_cents": max(1, abs(o["amount_cents"]) // (1 + r.i(3))),
        })
        rid += 1

    # payments: fungible money arriving over time, to be allocated against orders
    payments, pid = [], 9000
    n_pay = 70 + r.i(40)
    for _ in range(n_pay):
        paid = T0 + dt.timedelta(days=r.i(185), hours=r.i(24))
        payments.append({
            "payment_id": pid,
            "customer_id": 1 + r.i(n_cust + 3),
            "paid_at": paid.replace(microsecond=0).isoformat(sep=" "),
            "amount_cents": (500 + r.i(150000)),
            "currency": r.pick(CURRENCIES),
            "method": r.pick(["card", "wire", "ach"]),
        })
        pid += 1

    for name, rows, cols in [
        ("payments", payments, ["payment_id", "customer_id", "paid_at", "amount_cents", "currency", "method"]),
        ("customers", customers, ["customer_id", "region", "tier", "signed_up_at"]),
        ("orders", orders, ["order_id", "customer_id", "placed_at", "amount_cents", "currency", "status"]),
        ("refunds", refunds, ["refund_id", "order_id", "refunded_at", "amount_cents"]),
        ("fx_rates", fx, ["currency", "day", "rate_to_usd"]),
    ]:
        with (out / f"{name}.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    return {"customers": len(customers), "orders": len(orders),
            "refunds": len(refunds), "fx_rates": len(fx)}


if __name__ == "__main__":
    seed = int(sys.argv[1]); dest = pathlib.Path(sys.argv[2])
    print(seed, build(seed, dest))
