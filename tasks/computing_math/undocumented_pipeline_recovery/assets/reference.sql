-- The reference transformation, v2. Never shipped to the agent.
--
-- v1 embedded ten independent decisions and a strong agent fitted all of them in
-- twelve minutes by iterating against the worked examples. Independent decisions can
-- be searched one at a time; this version makes the computation stateful, so an
-- error in one row moves every later row.
--
-- Money arrives as payments and is consumed by orders in a running waterline. An
-- order is recognised only when cumulative demand up to and including it is covered
-- by cumulative payments, and it is recognised in the month of the payment that
-- crossed that line, not the month it was placed. Credit notes shrink demand before
-- the waterline is drawn, so a single credit note shifts which payment covers every
-- subsequent order.

CREATE OR REPLACE TABLE deduped AS
SELECT * EXCLUDE (rn) FROM (
  SELECT *, row_number() OVER (
      PARTITION BY order_id ORDER BY placed_at DESC, amount_cents ASC) AS rn
  FROM orders
) WHERE rn = 1;

CREATE OR REPLACE TABLE eligible AS
SELECT * FROM deduped
WHERE status IN ('paid', 'settled') AND amount_cents > 0;

CREATE OR REPLACE TABLE orders_usd AS
SELECT e.order_id, e.customer_id, e.placed_at,
       round(e.amount_cents * f.rate_to_usd) AS usd_cents
FROM eligible e
ASOF JOIN fx_rates f
  ON e.currency = f.currency AND CAST(e.placed_at AS DATE) >= f.day;

-- credit notes reduce what an order demands, converted at the refund's own day
CREATE OR REPLACE TABLE credits AS
SELECT r.order_id, sum(round(r.amount_cents * f.rate_to_usd)) AS credit_usd
FROM refunds r
JOIN eligible e ON e.order_id = r.order_id
ASOF JOIN fx_rates f
  ON e.currency = f.currency AND CAST(r.refunded_at AS DATE) >= f.day
WHERE r.refunded_at < e.placed_at + INTERVAL 30 DAY
GROUP BY r.order_id;

CREATE OR REPLACE TABLE demand AS
SELECT o.order_id, o.customer_id, o.placed_at,
       greatest(o.usd_cents - coalesce(c.credit_usd, 0), 0) AS net_usd,
       sum(greatest(o.usd_cents - coalesce(c.credit_usd, 0), 0)) OVER (
         PARTITION BY o.customer_id ORDER BY o.placed_at, o.order_id
         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_demand
FROM orders_usd o
LEFT JOIN credits c ON c.order_id = o.order_id;

CREATE OR REPLACE TABLE supply AS
SELECT p.payment_id, p.customer_id, p.paid_at,
       sum(round(p.amount_cents * f.rate_to_usd)) OVER (
         PARTITION BY p.customer_id ORDER BY p.paid_at, p.payment_id
         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_supply
FROM payments p
ASOF JOIN fx_rates f
  ON p.currency = f.currency AND CAST(p.paid_at AS DATE) >= f.day;

-- the payment that first carries cumulative supply up to this order's cumulative
-- demand is the one that recognises it; an order never covered is never recognised
CREATE OR REPLACE TABLE recognised AS
SELECT d.order_id, d.customer_id, d.net_usd, d.placed_at,
       (SELECT min(s.paid_at) FROM supply s
         WHERE s.customer_id = d.customer_id AND s.cum_supply >= d.cum_demand) AS covered_at
FROM demand d
WHERE d.net_usd > 0;

CREATE OR REPLACE TABLE result AS
SELECT month, customer_id, region, recognised_usd_cents, orders_recognised FROM (
  SELECT date_trunc('month', r.covered_at)::DATE AS month,
         r.customer_id,
         coalesce(c.region, 'UNKNOWN') AS region,
         CAST(sum(r.net_usd) AS BIGINT) AS recognised_usd_cents,
         CAST(count(*) AS BIGINT) AS orders_recognised
  FROM recognised r
  LEFT JOIN customers c ON c.customer_id = r.customer_id
  WHERE r.covered_at IS NOT NULL
    AND coalesce(c.tier, 'standard') <> 'internal'
  GROUP BY 1, 2, 3
)
ORDER BY month, customer_id;
