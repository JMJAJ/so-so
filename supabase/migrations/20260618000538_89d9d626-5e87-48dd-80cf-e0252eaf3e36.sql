CREATE OR REPLACE FUNCTION public.seed_demo_trading_data()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
  INSERT INTO public.positions (user_id, pair, asset_class, side, size, entry_price, current_price, pnl, pnl_pct, confidence, opened_at) VALUES
    -- Forex
    (NEW.id, 'EUR/USD', 'forex', 'long',  50000, 1.0824, 1.0871,  235.00,  0.43, 0.82, now() - interval '2 days'),
    (NEW.id, 'GBP/JPY', 'forex', 'short', 30000, 192.45, 191.20,  375.00,  0.65, 0.74, now() - interval '14 hours'),
    (NEW.id, 'USD/CHF', 'forex', 'long',  40000, 0.8812, 0.8795, -68.00, -0.19, 0.61, now() - interval '6 hours'),
    (NEW.id, 'AUD/USD', 'forex', 'long',  60000, 0.6612, 0.6648,  216.00,  0.54, 0.78, now() - interval '3 days'),
    (NEW.id, 'USD/JPY', 'forex', 'short', 35000, 156.20, 155.10,  385.00,  0.70, 0.88, now() - interval '1 day'),
    -- Crypto
    (NEW.id, 'BTC/USD', 'crypto','long',    0.5, 67200, 68950,    875.00,  2.60, 0.91, now() - interval '5 days'),
    (NEW.id, 'ETH/USD', 'crypto','long',    4.0,  3420,  3512,    368.00,  2.69, 0.84, now() - interval '4 days'),
    -- Commodities
    (NEW.id, 'XAU/USD', 'forex', 'long',     10, 2342.5, 2358.8,  163.00,  0.69, 0.79, now() - interval '8 hours'),
    -- Stocks
    (NEW.id, 'NVDA',    'stock', 'long',    120, 118.40, 124.85,  774.00,  5.45, 0.89, now() - interval '6 days'),
    (NEW.id, 'AAPL',    'stock', 'long',    100, 218.50, 221.30,  280.00,  1.28, 0.76, now() - interval '4 days'),
    (NEW.id, 'TSLA',    'stock', 'short',    50, 248.10, 242.55,  277.50,  2.24, 0.71, now() - interval '2 days'),
    (NEW.id, 'MSFT',    'stock', 'long',     40, 432.10, 438.20,  244.00,  1.41, 0.83, now() - interval '7 days'),
    (NEW.id, 'SPY',     'stock', 'long',     80, 548.30, 552.10,  304.00,  0.69, 0.68, now() - interval '10 days'),
    (NEW.id, 'AMD',     'stock', 'short',    60, 162.40, 158.90,  210.00,  2.15, 0.72, now() - interval '1 day');

  INSERT INTO public.trades (user_id, pair, side, size, entry_price, exit_price, pnl, closed_at) VALUES
    (NEW.id, 'EUR/USD','long',  50000, 1.0780, 1.0820, 200.00, now() - interval '1 day'),
    (NEW.id, 'GBP/USD','short', 40000, 1.2710, 1.2680, 120.00, now() - interval '2 days'),
    (NEW.id, 'USD/JPY','long',  30000, 154.20, 154.80, 116.50, now() - interval '3 days'),
    (NEW.id, 'NZD/USD','short', 25000, 0.6020, 0.6045, -62.50, now() - interval '4 days'),
    (NEW.id, 'BTC/USD','long',    0.3, 65800, 66950, 345.00, now() - interval '5 days'),
    (NEW.id, 'EUR/GBP','long',  35000, 0.8530, 0.8512, -63.00, now() - interval '6 days'),
    (NEW.id, 'USD/CAD','short', 30000, 1.3680, 1.3640, 120.00, now() - interval '7 days'),
    (NEW.id, 'NVDA',   'long',    100, 112.20, 118.40, 620.00, now() - interval '8 days'),
    (NEW.id, 'AAPL',   'long',     80, 214.00, 218.50, 360.00, now() - interval '9 days'),
    (NEW.id, 'TSLA',   'short',    40, 255.00, 248.10, 276.00, now() - interval '10 days'),
    (NEW.id, 'META',   'long',     30, 488.00, 495.20, 216.00, now() - interval '11 days'),
    (NEW.id, 'AMZN',   'long',     50, 178.20, 175.40, -140.00, now() - interval '12 days'),
    (NEW.id, 'GOOGL',  'long',     60, 165.30, 168.40, 186.00, now() - interval '13 days'),
    (NEW.id, 'SPY',    'long',     70, 542.10, 546.80, 329.00, now() - interval '14 days');

  INSERT INTO public.ai_logs (user_id, level, action, pair, message, created_at) VALUES
    (NEW.id, 'info',  'OPEN',    'USD/JPY', 'Short opened on bearish divergence (RSI 71, MACD cross).', now() - interval '1 day'),
    (NEW.id, 'info',  'OPEN',    'NVDA',    'Long opened on earnings beat + AI capex commentary. Target $135.', now() - interval '6 days'),
    (NEW.id, 'info',  'OPEN',    'BTC/USD', 'Long opened on breakout above 67k resistance with strong volume.', now() - interval '5 days'),
    (NEW.id, 'warn',  'HOLD',    'USD/CHF', 'Position underwater; volatility low — holding through Asia session.', now() - interval '4 hours'),
    (NEW.id, 'info',  'SIGNAL',  'EUR/USD', 'Bullish continuation pattern detected on H4. Confidence 0.82.', now() - interval '2 hours'),
    (NEW.id, 'info',  'CLOSE',   'GBP/USD','Target reached at 1.2680. Closed +120 USD.', now() - interval '2 days'),
    (NEW.id, 'error', 'SKIP',    'NZD/USD','Spread widened beyond risk tolerance — skipped entry.', now() - interval '30 minutes'),
    (NEW.id, 'info',  'REBAL',    NULL,    'Portfolio rebalanced: reduced JPY exposure by 12%, increased tech equity 8%.', now() - interval '1 hour'),
    (NEW.id, 'info',  'SIGNAL',  'XAU/USD','Gold momentum strong on dollar weakness. Adding to long.', now() - interval '10 minutes'),
    (NEW.id, 'warn',  'RISK',    'TSLA',   'Implied vol spiked 18%. Tightening stop to entry.', now() - interval '45 minutes'),
    (NEW.id, 'info',  'SIGNAL',  'AAPL',   'Mean reversion setup on 1H. Confidence 0.76.', now() - interval '20 minutes'),
    (NEW.id, 'info',  'OPEN',    'MSFT',   'Long opened — Azure growth thesis intact, breakout above $432.', now() - interval '7 days');

  RETURN NEW;
END;
$function$;