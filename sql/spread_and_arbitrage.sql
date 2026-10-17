-- 1. Hourly FR-DE spread (cross-border price convergence).
-- 2. Daily battery arbitrage value: a 1 MW / 2 MWh battery charging in the two
--    cheapest hours and discharging in the two most expensive ones, at 88%
--    round-trip efficiency. Rough upper bound, ignoring degradation and fees.
WITH hourly AS (
  SELECT bidding_zone,
         delivery_date,
         date_trunc('hour', delivery_start) AS hour_utc,
         avg(price_eur_mwh)                 AS price
  FROM day_ahead_prices
  WHERE delivery_date >= current_date - INTERVAL '30' DAY
  GROUP BY 1, 2, 3
),
spread AS (
  SELECT fr.delivery_date, fr.hour_utc, fr.price AS fr_price, de.price AS de_price, fr.price - de.price AS fr_minus_de
  FROM hourly fr
  JOIN hourly de ON de.hour_utc = fr.hour_utc AND de.bidding_zone = 'DE-LU'
  WHERE fr.bidding_zone = 'FR'
),
ranked AS (
  SELECT bidding_zone, delivery_date, price,
         row_number() OVER (PARTITION BY bidding_zone, delivery_date ORDER BY price ASC)  AS cheap_rank,
         row_number() OVER (PARTITION BY bidding_zone, delivery_date ORDER BY price DESC) AS dear_rank
  FROM hourly
)
SELECT r.bidding_zone,
       r.delivery_date,
       round(sum(CASE WHEN dear_rank <= 2 THEN price END) * 0.88
           - sum(CASE WHEN cheap_rank <= 2 THEN price END), 2) AS arbitrage_eur_per_mw,
       round(avg(s.fr_minus_de), 2)                           AS avg_fr_minus_de
FROM ranked r
LEFT JOIN spread s ON s.delivery_date = r.delivery_date
GROUP BY 1, 2
ORDER BY 2 DESC, 1;
