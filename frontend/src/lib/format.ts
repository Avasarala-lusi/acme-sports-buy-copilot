const nf = new Intl.NumberFormat("en-US");

export const num = (n: number | null | undefined, digits = 0) =>
  n == null || Number.isNaN(n) ? "—" : new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n);

export const int = (n: number | null | undefined) => (n == null ? "—" : nf.format(Math.round(n)));

export const money = (n: number | null | undefined) => {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n < 0 ? "−" : "";
  return `${sign}$${nf.format(Math.round(Math.abs(n)))}`;
};

export const moneyShort = (n: number | null | undefined) => {
  if (n == null || Number.isNaN(n)) return "—";
  const a = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)}k`;
  return `${sign}$${a.toFixed(0)}`;
};

export const pct = (n: number | null | undefined, digits = 1) => (n == null ? "—" : `${n.toFixed(digits)}%`);

// The API sends naive timestamps that are already UTC; read them as UTC so days don't shift.
const parse = (iso: string) => new Date(/([zZ]|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);

export const date = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = parse(iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
};

export const shortDate = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = parse(iso);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" });
};

export const splitList = (s: string | null | undefined) =>
  (s ?? "").split(" | ").map((x) => x.trim()).filter(Boolean);
