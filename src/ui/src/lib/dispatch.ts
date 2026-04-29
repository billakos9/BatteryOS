// Numeric formatting helpers used across the UI.
// Dispatch results are now always fetched from /api/* — no client-side
// simulation lives here.

export function fmtNum(n: number | null | undefined, dp = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n < 0 ? "−" : "";
  const a = Math.abs(n);
  return sign + a.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

export function fmtEur(n: number | null | undefined, dp = 0): string {
  return "€" + fmtNum(n, dp);
}
