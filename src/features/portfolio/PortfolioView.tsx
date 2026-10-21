import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { LineChart, chartColors } from "@/features/charts/svg";
import {
  Badge,
  DirectionBadge,
  Empty,
  ErrorNote,
  Loading,
  PageHeading,
  Panel,
  Stat,
  Td,
  Th,
  TableWrap,
} from "@/features/shell/ui";
import { MarketChip } from "@/features/markets/MarketChip";
import { api } from "@/lib/api";
import { ago, humanize, money, num, pct, price, shortDate, tone } from "@/lib/format";
import { useNav } from "@/lib/nav";

export default function PortfolioView() {
  const { openAsset } = useNav();
  const client = useQueryClient();
  const portfolio = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
    refetchInterval: 60_000,
  });
  const close = useMutation({
    mutationFn: api.closePosition,
    onSuccess: () => {
      toast.success("Position closed");
      void client.invalidateQueries();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (portfolio.isLoading) return <Loading />;
  if (portfolio.error) return <ErrorNote error={portfolio.error} />;
  const data = portfolio.data!;
  const curve = data.equity_curve ?? [];

  return (
    <div className="space-y-4">
      <PageHeading
        title="Paper portfolio"
        subtitle="With autopilot on, every AI recommendation opens a paper position sized so hitting the stop loses ~1% of equity. Fills use delayed quotes plus slippage; orders placed while a market is closed fill at the next open."
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        {[
          [
            "Equity",
            money(data.equity),
            pct(data.return_pct / 100, 2) + " total",
            tone(data.return_pct),
          ],
          [
            "Realized",
            money(data.realized, true),
            `${data.trade_count} trades`,
            tone(data.realized),
          ],
          [
            "Open P&L",
            money(data.unrealized, true),
            `${data.open_count} open · ${data.pending_count} pending`,
            tone(data.unrealized),
          ],
          ["Exposure", `${num(data.exposure_pct, 0)}%`, money(data.exposure), ""],
          [
            "Win rate",
            data.win_rate == null ? "—" : `${num(data.win_rate, 0)}%`,
            "closed trades",
            "",
          ],
          [
            "Avg win / loss",
            data.avg_win == null ? "—" : `${money(data.avg_win)} / ${money(data.avg_loss)}`,
            "net of fees",
            "",
          ],
        ].map(([label, value, hint, className]) => (
          <div key={label} className="terminal-panel p-3">
            <Stat label={label} value={value} hint={hint} valueClassName={className} />
          </div>
        ))}
      </div>
      <Panel
        title="Equity vs S&P 500"
        subtitle="Daily snapshot of paper equity against buying SPY on day one."
      >
        <LineChart
          zero
          format={(v) => `${v.toFixed(1)}%`}
          series={[
            {
              name: "Paper account",
              color: chartColors.AMBER,
              points: curve.map((p) => ({ x: p.date, y: p.return_pct })),
            },
            {
              name: "SPY",
              color: chartColors.MUTED,
              points: curve.map((p) => ({ x: p.date, y: p.spy_return_pct })),
            },
          ]}
        />
      </Panel>
      <Panel title="Positions">
        {data.positions.length === 0 ? (
          <Empty title="No positions">
            Recommendations open positions automatically when autopilot is on (Settings).
          </Empty>
        ) : (
          <TableWrap>
            <thead>
              <tr>
                <Th>Asset</Th>
                <Th>Side</Th>
                <Th>Status</Th>
                <Th right>Qty</Th>
                <Th right>Entry</Th>
                <Th right>Mark</Th>
                <Th right>P&L</Th>
                <Th right>Stop</Th>
                <Th right>Target</Th>
                <Th>Expires</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {data.positions.map((position) => (
                <tr key={position.id}>
                  <Td>
                    <button
                      className="font-bold hover:text-primary"
                      onClick={() => openAsset(position.instrument_id)}
                    >
                      {position.symbol}
                    </button>
                    <MarketChip marketId={position.market} className="mt-0.5 block" />
                  </Td>
                  <Td>
                    <DirectionBadge direction={position.side} />
                  </Td>
                  <Td>
                    <Badge tone={position.status === "open" ? "amber" : "neutral"}>
                      {position.status}
                    </Badge>
                  </Td>
                  <Td right>{num(position.quantity, position.quantity < 10 ? 4 : 0)}</Td>
                  <Td right>{price(position.entry_price)}</Td>
                  <Td right>{price(position.current_price)}</Td>
                  <Td right className={tone(position.pnl)}>
                    {money(position.pnl, true)}{" "}
                    <span className="text-[10px]">({num(position.pnl_pct, 1)}%)</span>
                  </Td>
                  <Td right className="text-bear">
                    {price(position.stop)}
                  </Td>
                  <Td right className="text-bull">
                    {price(position.target)}
                  </Td>
                  <Td className="text-[10px] text-muted-foreground">{ago(position.expires_at)}</Td>
                  <Td>
                    <button
                      className="danger-button !py-1"
                      disabled={close.isPending}
                      onClick={() => {
                        if (window.confirm(`Close ${position.symbol} at the current price?`))
                          close.mutate(position.id);
                      }}
                    >
                      {position.status === "pending" ? "Cancel" : "Close"}
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
      <Panel title="Closed trades">
        {!data.trades?.length ? (
          <Empty title="No closed trades yet" />
        ) : (
          <TableWrap>
            <thead>
              <tr>
                <Th>Closed</Th>
                <Th>Asset</Th>
                <Th>Side</Th>
                <Th right>Entry</Th>
                <Th right>Exit</Th>
                <Th right>Net P&L</Th>
                <Th>Reason</Th>
              </tr>
            </thead>
            <tbody>
              {data.trades.map((trade) => (
                <tr key={trade.id}>
                  <Td>{shortDate(trade.closed_at)}</Td>
                  <Td>
                    <button
                      className="font-bold hover:text-primary"
                      onClick={() => openAsset(trade.instrument_id)}
                    >
                      {trade.symbol}
                    </button>
                  </Td>
                  <Td>
                    <DirectionBadge direction={trade.side} />
                  </Td>
                  <Td right>{price(trade.entry_price)}</Td>
                  <Td right>{price(trade.exit_price)}</Td>
                  <Td right className={tone(trade.net_pnl)}>
                    {money(trade.net_pnl, true)}
                  </Td>
                  <Td>{humanize(trade.exit_reason)}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
    </div>
  );
}
