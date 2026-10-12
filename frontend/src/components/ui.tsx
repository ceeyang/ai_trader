import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-slate-600">{label}</span>
      {children}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`rounded border border-slate-300 bg-white px-2 py-1 ${props.className ?? ""}`} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`rounded border border-slate-300 bg-white px-2 py-1 ${props.className ?? ""}`} />;
}

export function Button({ children, ...props }: { children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50 ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
      {message}
    </div>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {title && <h2 className="mb-3 text-base font-semibold">{title}</h2>}
      {children}
    </section>
  );
}

export function errorMessage(err: unknown): string {
  if (err && typeof err === "object" && "detail" in err) return String((err as { detail: unknown }).detail);
  if (err instanceof Error) return err.message;
  return String(err);
}

export const fmt = {
  num: (v: number | null | undefined, digits = 2) => (v == null || Number.isNaN(v) ? "-" : v.toFixed(digits)),
  pct: (v: number | null | undefined, digits = 2) => (v == null || Number.isNaN(v) ? "-" : `${v.toFixed(digits)}%`),
  ratio: (v: number | null | undefined, digits = 2) => (v == null || Number.isNaN(v) ? "-" : `${(v * 100).toFixed(digits)}%`),
  date: (unix: number) => new Date(unix * 1000).toISOString().slice(0, 16).replace("T", " "),
};

export function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}
