-- grain: seller_id
-- Net sales by seller for completed June 2026 orders, minus refunds before July 1.
WITH refund_totals AS (
    SELECT order_id, SUM(refund_cents) AS refunded_cents
    FROM refunds
    WHERE refund_date < '2026-07-01'
    GROUP BY order_id
)
SELECT o.seller_id,
       COUNT(o.order_id) AS completed_orders,
       SUM(o.gross_cents - COALESCE(r.refunded_cents, 0)) AS net_cents
FROM orders o
LEFT JOIN refund_totals r ON o.order_id = r.order_id
WHERE o.status = 'completed'
  AND o.order_date >= '2026-06-01' AND o.order_date < '2026-07-01'
GROUP BY o.seller_id
ORDER BY net_cents DESC, o.seller_id;
