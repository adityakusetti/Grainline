-- grain: seller_id
-- Same report, but joins refunds directly: an order with two refunds is counted twice.
SELECT o.seller_id,
       COUNT(*) AS completed_orders,
       SUM(o.gross_cents - COALESCE(r.refund_cents, 0)) AS net_cents
FROM orders o
LEFT JOIN refunds r ON o.order_id = r.order_id
WHERE o.status = 'completed'
  AND o.order_date >= '2026-06-01' AND o.order_date < '2026-07-01'
  AND r.refund_date < '2026-07-01'
GROUP BY o.seller_id
ORDER BY net_cents DESC, o.seller_id;
