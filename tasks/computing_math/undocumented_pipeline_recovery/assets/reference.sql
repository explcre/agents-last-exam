-- The reference transformation. Never shipped to the agent.
--
-- Every step here is a decision a real revenue pipeline has to make and that is
-- invisible from the output alone unless you look carefully:
--   * an order id can appear twice; the later row wins, ties broken by the smaller amount
--   * only paid or settled orders with a positive amount count
--   * money converts at the rate for that day, or the most recent earlier day if the
--     day has no rate at all (weekends have none)
--   * a refund converts at the rate for the REFUND's day, not the order's
--   * a refund counts only if it lands within 30 days of the order
--   * an unknown customer is reported as UNKNOWN/standard rather than dropped
--   * internal accounts are excluded entirely
--   * a customer-month is reported only when it nets out above zero

CREATE OR REPLACE TABLE deduped AS
SELECT * EXCLUDE (rn) FROM (
  SELECT *, row_number() OVER (
      PARTITION BY order_id ORDER BY placed_at DESC, amount_cents ASC) AS rn
  FROM orders
) WHERE rn = 1;

CREATE OR REPLACE TABLE eligible AS
SELECT * FROM deduped
WHERE status IN ('paid', 'settled') AND amount_cents > 0;

-- as-of lookup: the rate on the day, else the most recent earlier day
CREATE OR REPLACE TABLE orders_usd AS
SELECT e.order_id, e.customer_id, e.placed_at, e.amount_cents, e.currency,
       round(e.amount_cents * f.rate_to_usd) AS usd_cents
FROM eligible e
ASOF JOIN fx_rates f
  ON e.currency = f.currency AND CAST(e.placed_at AS DATE) >= f.day;

CREATE OR REPLACE TABLE refunds_usd AS
SELECT r.order_id, round(r.amount_cents * f.rate_to_usd) AS usd_cents
FROM refunds r
JOIN eligible e ON e.order_id = r.order_id
ASOF JOIN fx_rates f
  ON e.currency = f.currency AND CAST(r.refunded_at AS DATE) >= f.day
WHERE r.refunded_at < e.placed_at + INTERVAL 30 DAY;

CREATE OR REPLACE TABLE result AS
SELECT month, customer_id, region, net_usd_cents FROM (
  SELECT date_trunc('month', o.placed_at)::DATE AS month,
         o.customer_id,
         coalesce(c.region, 'UNKNOWN') AS region,
         CAST(sum(o.usd_cents) - coalesce(sum(rf.refunded), 0) AS BIGINT) AS net_usd_cents
  FROM orders_usd o
  LEFT JOIN customers c ON c.customer_id = o.customer_id
  LEFT JOIN (SELECT order_id, sum(usd_cents) AS refunded FROM refunds_usd GROUP BY order_id) rf
         ON rf.order_id = o.order_id
  WHERE coalesce(c.tier, 'standard') <> 'internal'
  GROUP BY 1, 2, 3
)
WHERE net_usd_cents > 0
ORDER BY month, customer_id;
