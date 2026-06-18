
-- POSITIONS
CREATE TABLE public.positions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  pair TEXT NOT NULL,
  asset_class TEXT NOT NULL DEFAULT 'forex',
  side TEXT NOT NULL CHECK (side IN ('long','short')),
  size NUMERIC NOT NULL,
  entry_price NUMERIC NOT NULL,
  current_price NUMERIC NOT NULL,
  pnl NUMERIC NOT NULL DEFAULT 0,
  pnl_pct NUMERIC NOT NULL DEFAULT 0,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  confidence NUMERIC NOT NULL DEFAULT 0.7
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.positions TO authenticated;
GRANT ALL ON public.positions TO service_role;
ALTER TABLE public.positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own positions" ON public.positions FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- TRADES (history)
CREATE TABLE public.trades (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  pair TEXT NOT NULL,
  side TEXT NOT NULL,
  size NUMERIC NOT NULL,
  entry_price NUMERIC NOT NULL,
  exit_price NUMERIC NOT NULL,
  pnl NUMERIC NOT NULL,
  closed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.trades TO authenticated;
GRANT ALL ON public.trades TO service_role;
ALTER TABLE public.trades ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own trades" ON public.trades FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- AI LOGS
CREATE TABLE public.ai_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  level TEXT NOT NULL DEFAULT 'info',
  action TEXT NOT NULL,
  pair TEXT,
  message TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.ai_logs TO authenticated;
GRANT ALL ON public.ai_logs TO service_role;
ALTER TABLE public.ai_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own ai_logs" ON public.ai_logs FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Seed demo data on user signup
CREATE OR REPLACE FUNCTION public.seed_demo_trading_data()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.positions (user_id, pair, asset_class, side, size, entry_price, current_price, pnl, pnl_pct, confidence, opened_at) VALUES
    (NEW.id, 'EUR/USD', 'forex', 'long',  50000, 1.0824, 1.0871,  235.00,  0.43, 0.82, now() - interval '2 days'),
    (NEW.id, 'GBP/JPY', 'forex', 'short', 30000, 192.45, 191.20,  375.00,  0.65, 0.74, now() - interval '14 hours'),
    (NEW.id, 'USD/CHF', 'forex', 'long',  40000, 0.8812, 0.8795, -68.00, -0.19, 0.61, now() - interval '6 hours'),
    (NEW.id, 'AUD/USD', 'forex', 'long',  60000, 0.6612, 0.6648,  216.00,  0.54, 0.78, now() - interval '3 days'),
    (NEW.id, 'USD/JPY', 'forex', 'short', 35000, 156.20, 155.10,  385.00,  0.70, 0.88, now() - interval '1 day'),
    (NEW.id, 'BTC/USD', 'crypto','long',    0.5, 67200, 68950,    875.00,  2.60, 0.91, now() - interval '5 days'),
    (NEW.id, 'ETH/USD', 'crypto','long',    4.0,  3420,  3512,    368.00,  2.69, 0.84, now() - interval '4 days'),
    (NEW.id, 'XAU/USD', 'forex', 'long',     10, 2342.5, 2358.8,  163.00,  0.69, 0.79, now() - interval '8 hours');

  INSERT INTO public.trades (user_id, pair, side, size, entry_price, exit_price, pnl, closed_at) VALUES
    (NEW.id, 'EUR/USD','long',  50000, 1.0780, 1.0820, 200.00, now() - interval '1 day'),
    (NEW.id, 'GBP/USD','short', 40000, 1.2710, 1.2680, 120.00, now() - interval '2 days'),
    (NEW.id, 'USD/JPY','long',  30000, 154.20, 154.80, 116.50, now() - interval '3 days'),
    (NEW.id, 'NZD/USD','short', 25000, 0.6020, 0.6045, -62.50, now() - interval '4 days'),
    (NEW.id, 'BTC/USD','long',    0.3, 65800, 66950, 345.00, now() - interval '5 days'),
    (NEW.id, 'EUR/GBP','long',  35000, 0.8530, 0.8512, -63.00, now() - interval '6 days'),
    (NEW.id, 'USD/CAD','short', 30000, 1.3680, 1.3640, 120.00, now() - interval '7 days');

  INSERT INTO public.ai_logs (user_id, level, action, pair, message, created_at) VALUES
    (NEW.id, 'info',  'OPEN',    'USD/JPY', 'Short opened on bearish divergence (RSI 71, MACD cross).', now() - interval '1 day'),
    (NEW.id, 'info',  'OPEN',    'BTC/USD', 'Long opened on breakout above 67k resistance with strong volume.', now() - interval '5 days'),
    (NEW.id, 'warn',  'HOLD',    'USD/CHF', 'Position underwater; volatility low — holding through Asia session.', now() - interval '4 hours'),
    (NEW.id, 'info',  'SIGNAL',  'EUR/USD', 'Bullish continuation pattern detected on H4. Confidence 0.82.', now() - interval '2 hours'),
    (NEW.id, 'info',  'CLOSE',   'GBP/USD','Target reached at 1.2680. Closed +120 USD.', now() - interval '2 days'),
    (NEW.id, 'error', 'SKIP',    'NZD/USD','Spread widened beyond risk tolerance — skipped entry.', now() - interval '30 minutes'),
    (NEW.id, 'info',  'REBAL',    NULL,    'Portfolio rebalanced: reduced JPY exposure by 12%.', now() - interval '1 hour'),
    (NEW.id, 'info',  'SIGNAL',  'XAU/USD','Gold momentum strong on dollar weakness. Adding to long.', now() - interval '10 minutes');

  RETURN NEW;
END;
$$;

CREATE TRIGGER on_auth_user_created_seed_trading
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.seed_demo_trading_data();
