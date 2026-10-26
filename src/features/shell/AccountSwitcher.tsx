import { useQuery } from "@tanstack/react-query";
import { Wallet } from "lucide-react";

import { currentAccount, switchAccount } from "@/lib/account";
import { api } from "@/lib/api";
import { money } from "@/lib/format";

/** Which paper account the whole app is showing and trading in. */
export function AccountSwitcher() {
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const list = accounts.data?.accounts ?? [];
  if (list.length === 0) return null;
  const active = currentAccount();
  return (
    <label
      className="flex shrink-0 items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
      title="Paper account in use: portfolio, trades and chat orders go here"
    >
      <Wallet className="h-3.5 w-3.5" />
      <select
        className="terminal-select !min-h-0 !py-1 text-[11px] normal-case tracking-normal"
        value={list.some((a) => a.id === active) ? active : "main"}
        onChange={(e) => switchAccount(e.target.value)}
      >
        {list.map((account) => (
          <option key={account.id} value={account.id}>
            {account.name} · {money(account.equity)}
            {account.gate === "any" ? " · any trade" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
