/** The paper account the UI is working in. Sent as X-Nexus-Account with every API request;
 * switching reloads the page so every view refetches for the new account. */
const STORAGE_KEY = "nexus.account";

export function currentAccount(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || "main";
  } catch {
    return "main";
  }
}

export function switchAccount(id: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Storage blocked: the switch won't stick, but reloading still shows the default account.
  }
  window.location.reload();
}

export function accountHeaders(init?: RequestInit): RequestInit {
  return {
    ...init,
    headers: {
      ...(init?.headers as Record<string, string> | undefined),
      "X-Nexus-Account": currentAccount(),
    },
  };
}
