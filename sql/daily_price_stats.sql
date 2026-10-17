-- Daily statistics per bidding zone over the last 30 days.
SELECT bidding_zone,
       delivery_date,
       count(*)                                   AS intervals,
       round(avg(price_eur_mwh), 2)               AS baseload_eur_mwh,
       round(min(price_eur_mwh), 2)               AS min_eur_mwh,
       round(max(price_eur_mwh), 2)               AS max_eur_mwh,
       count_if(price_eur_mwh < 0)                AS negative_intervals
FROM day_ahead_prices
WHERE delivery_date >= current_date - INTERVAL '30' DAY
GROUP BY 1, 2
ORDER BY 2 DESC, 1;
