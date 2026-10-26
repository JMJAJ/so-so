import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Badge, Loading, Panel, Td, Th, TableWrap } from "@/features/shell/ui";
import { currentAccount, switchAccount } from "@/lib/account";
import { api } from "@/lib/api";
import { money, pct, tone } from "@/lib/format";
import type { PaperAccount } from "@/lib/types";

const GATE_HELP = {
  strict: "only trades with positive expected value",
  any: "any trade you ask for (still shows the honest odds)",
} as const;

/** Create, switch, edit, reset and delete paper trading accounts. */
export function AccountsPanel() {
  const client = useQueryClient();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const [draft, setDraft] = useState({ name: "", starting_equity: "1000", gate: "strict" });
  const refresh = () => void client.invalidateQueries();
  const create = useMutation({
    mutationFn: () => api.createAccount(draft),
    onSuccess: (account) => {
      toast.success(`Created ${account.name}`);
      setDraft({ name: "", starting_equity: "1000", gate: "strict" });
      refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <Panel
      title="Paper accounts"
      subtitle="Each account has its own money, positions, trades and history. AI calls are shared research: any account can trade them, and the daily analyst trades its calls in every account with autopilot on."
    >
      {accounts.isLoading ? (
        <Loading />
      ) : (
        <div className="space-y-4">
          <TableWrap>
            <thead>
              <tr>
                <Th>Account</Th>
                <Th right>Starting money</Th>
                <Th right>Equity</Th>
                <Th>Trade gate</Th>
                <Th>Autopilot</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {(accounts.data?.accounts ?? []).map((account) => (
                <AccountRow
                  key={account.id}
                  account={account}
                  active={account.id === currentAccount()}
                  onChanged={refresh}
                />
              ))}
            </tbody>
          </TableWrap>
          <form
            className="flex flex-wrap items-end gap-2 border-t border-border pt-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <label className="space-y-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              <span className="block">New account</span>
              <input
                className="terminal-input"
                placeholder="Name"
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </label>
            <label className="space-y-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              <span className="block">Starting money ($)</span>
              <input
                className="terminal-input w-32"
                type="number"
                min="100"
                step="100"
                value={draft.starting_equity}
                onChange={(e) => setDraft({ ...draft, starting_equity: e.target.value })}
              />
            </label>
            <label className="space-y-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              <span className="block">Trade gate</span>
              <select
                className="terminal-select"
                value={draft.gate}
                onChange={(e) => setDraft({ ...draft, gate: e.target.value })}
              >
                <option value="strict">Strict: {GATE_HELP.strict}</option>
                <option value="any">Any: {GATE_HELP.any}</option>
              </select>
            </label>
            <button className="primary-button" disabled={!draft.name.trim() || create.isPending}>
              {create.isPending ? "Creating…" : "Create account"}
            </button>
          </form>
        </div>
      )}
    </Panel>
  );
}

function AccountRow({
  account,
  active,
  onChanged,
}: {
  account: PaperAccount;
  active: boolean;
  onChanged: () => void;
}) {
  const [start, setStart] = useState(String(account.starting_equity));
  const update = useMutation({
    mutationFn: (fields: Partial<PaperAccount>) => api.updateAccount(account.id, fields),
    onSuccess: onChanged,
    onError: (error: Error) => toast.error(error.message),
  });
  const reset = useMutation({
    mutationFn: () => api.resetAccount(account.id, Number(start) || undefined),
    onSuccess: (result) => {
      toast.success(
        `${account.name} reset to ${money(result.equity)} (${result.closed_positions} positions closed)`,
      );
      onChanged();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteAccount(account.id),
    onSuccess: () => {
      toast.success(`Deleted ${account.name}`);
      if (active) switchAccount("main");
      else onChanged();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <tr>
      <Td>
        <div className="flex items-center gap-2 font-bold">
          {account.name}
          {active && <Badge tone="amber">in use</Badge>}
        </div>
        <div className="text-[10px] text-muted-foreground">
          {account.positions} positions · {account.trade_count} closed trades
        </div>
      </Td>
      <Td right>
        <input
          className="terminal-input w-28 text-right"
          type="number"
          min="100"
          step="100"
          value={start}
          onChange={(e) => setStart(e.target.value)}
          onBlur={() => {
            if (Number(start) !== account.starting_equity)
              update.mutate({ starting_equity: Number(start) });
          }}
        />
      </Td>
      <Td right>
        {money(account.equity)}{" "}
        <span className={tone(account.return_pct)}>{pct(account.return_pct / 100)}</span>
      </Td>
      <Td>
        <select
          className="terminal-select"
          value={account.gate}
          onChange={(e) => update.mutate({ gate: e.target.value as PaperAccount["gate"] })}
          title={GATE_HELP[account.gate]}
        >
          <option value="strict">Strict</option>
          <option value="any">Any trade</option>
        </select>
      </Td>
      <Td>
        <select
          className="terminal-select"
          value={account.autopilot ? "on" : "off"}
          onChange={(e) => update.mutate({ autopilot: e.target.value === "on" })}
        >
          <option value="on">On</option>
          <option value="off">Off</option>
        </select>
      </Td>
      <Td>
        <div className="flex justify-end gap-1">
          {!active && (
            <button
              className="secondary-button !px-2 !py-1"
              onClick={() => switchAccount(account.id)}
            >
              Use
            </button>
          )}
          <button
            className="secondary-button !px-2 !py-1 hover:!border-bear hover:!text-bear"
            disabled={reset.isPending}
            onClick={() => {
              if (
                window.confirm(
                  `Reset ${account.name} to ${money(Number(start))}? Its positions are closed at the current price and its history starts over.`,
                )
              )
                reset.mutate();
            }}
          >
            Reset
          </button>
          {account.id !== "main" && (
            <button
              className="secondary-button !px-2 !py-1 hover:!border-bear hover:!text-bear"
              disabled={remove.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `Delete ${account.name}? Its positions, trades and history are removed for good.`,
                  )
                )
                  remove.mutate();
              }}
            >
              Delete
            </button>
          )}
        </div>
      </Td>
    </tr>
  );
}
