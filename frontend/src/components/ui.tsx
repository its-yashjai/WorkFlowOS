import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { X, LoaderCircle } from "lucide-react";
import { ReactNode, useEffect, useRef, useState } from "react";
import clsx from "clsx";

export const spring = { type: "spring", stiffness: 420, damping: 34 } as const;
export const softSpring = { type: "spring", stiffness: 220, damping: 28 } as const;

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "quiet" | "danger" | "good"; size?: "sm" | "md"; icon?: ReactNode; busy?: boolean;
};
export function Button({ variant = "ghost", size = "md", icon, busy, className, children, ...p }: BtnProps) {
  return (
    <motion.button
      whileTap={{ scale: 0.96 }}
      {...(p as object)}
      disabled={p.disabled || busy}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-colors disabled:opacity-50 select-none",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-volt text-ink hover:bg-[#95a2ff]",
        variant === "ghost" && "border border-white/12 bg-white/[0.04] hover:bg-white/[0.09] text-paper",
        variant === "quiet" && "text-mist hover:text-paper hover:bg-white/[0.06]",
        variant === "danger" && "border border-bad/30 text-bad hover:bg-bad/10",
        variant === "good" && "bg-flow text-ink hover:bg-[#5fe3d4]",
        className,
      )}
    >
      {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </motion.button>
  );
}

export function Chip({ children, tone = "mist", className }: { children: ReactNode; tone?: "mist" | "flow" | "hand" | "bad" | "volt" | "ok"; className?: string }) {
  const map = {
    mist: "bg-white/[0.06] text-mist",
    flow: "bg-flow/12 text-flow",
    hand: "bg-hand/12 text-hand",
    bad: "bg-bad/12 text-bad",
    volt: "bg-volt/15 text-volt",
    ok: "bg-ok/12 text-ok",
  };
  return <span className={clsx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap", map[tone], className)}>{children}</span>;
}

export function Segmented<T extends string>({ value, options, onChange, layoutId, size = "md" }: {
  value: T; options: { value: T; label: string; icon?: ReactNode }[]; onChange: (v: T) => void; layoutId: string; size?: "sm" | "md";
}) {
  return (
    <div className="relative inline-flex rounded-xl bg-white/[0.05] p-1 border border-white/10" role="radiogroup">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={o.value === value} onClick={() => onChange(o.value)}
          className={clsx("relative z-10 flex items-center gap-1.5 rounded-lg font-medium transition-colors",
            size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-[13px]",
            o.value === value ? "text-ink" : "text-mist hover:text-paper")}>
          {o.value === value && (
            <motion.span layoutId={layoutId} transition={spring} className="absolute inset-0 -z-10 rounded-lg bg-paper" />
          )}
          {o.icon}{o.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}
      className={clsx("relative h-6 w-11 rounded-full transition-colors", on ? "bg-flow" : "bg-white/15")}>
      <motion.span layout transition={spring} className={clsx("absolute top-0.5 h-5 w-5 rounded-full bg-paper shadow", on ? "right-0.5" : "left-0.5")} />
    </button>
  );
}

export function Sheet({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-[#05070f]/75 backdrop-blur-sm" onClick={onClose} />
          <motion.div role="dialog" aria-modal aria-label={title}
            initial={{ y: 40, opacity: 0, scale: 0.98 }} animate={{ y: 0, opacity: 1, scale: 1 }} exit={{ y: 30, opacity: 0, scale: 0.98 }}
            transition={softSpring}
            className={clsx("panel relative w-full max-h-[92vh] overflow-y-auto scroll-thin rounded-t-3xl sm:rounded-3xl p-5 sm:p-6 safe-bottom",
              wide ? "sm:max-w-2xl" : "sm:max-w-lg")}>
            <div className="mb-4 flex items-center justify-between gap-4">
              <h2 className="font-display text-xl font-semibold tracking-tight">{title}</h2>
              <button onClick={onClose} aria-label="Close" className="rounded-full p-1.5 text-mist hover:bg-white/10 hover:text-paper"><X className="h-5 w-5" /></button>
            </div>
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function CountUp({ value, suffix = "", className }: { value: number; suffix?: string; className?: string }) {
  const reduce = useReducedMotion();
  const [v, setV] = useState(reduce ? value : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reduce) { setV(value); return; }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / 900);
      const e = 1 - Math.pow(1 - k, 3);
      setV(Math.round(a + (value - a) * e));
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, reduce]);
  return <span className={className}>{v}{suffix}</span>;
}

export function Tabs<T extends string>({ tabs, value, onChange, id }: { tabs: { value: T; label: string; badge?: number | boolean }[]; value: T; onChange: (v: T) => void; id: string }) {
  return (
    <div className="no-scrollbar flex gap-1 overflow-x-auto border-b hairline" role="tablist">
      {tabs.map((t) => (
        <button key={t.value} role="tab" aria-selected={t.value === value} onClick={() => onChange(t.value)}
          className={clsx("relative flex shrink-0 items-center gap-1.5 px-3 pb-3 pt-2 text-sm font-medium transition-colors",
            t.value === value ? "text-paper" : "text-faint hover:text-mist")}>
          {t.label}
          {t.badge ? <span className="grid h-4 min-w-4 place-items-center rounded-full bg-hand px-1 text-[10px] font-bold text-ink">{t.badge === true ? "" : t.badge}</span> : null}
          {t.value === value && <motion.span layoutId={id} transition={spring} className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-paper" />}
        </button>
      ))}
    </div>
  );
}

export function Empty({ icon, title, body, action }: { icon: ReactNode; title: string; body: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-white/[0.06] text-mist">{icon}</div>
      <p className="font-display text-lg font-semibold">{title}</p>
      <p className="mt-1 max-w-sm text-sm text-mist">{body}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={clsx("h-5 w-5 animate-spin text-mist", className)} />;
}

export function ConfidenceBar({ value, threshold }: { value: number; threshold?: number }) {
  const tone = value >= (threshold ?? 0.8) ? "bg-flow" : value >= 0.5 ? "bg-hand" : "bg-bad";
  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-white/10">
      <motion.div className={clsx("h-full rounded-full", tone)} initial={{ width: 0 }} animate={{ width: `${Math.round(value * 100)}%` }} transition={softSpring} />
      {threshold != null && <span className="absolute top-0 h-full w-px bg-paper/70" style={{ left: `${threshold * 100}%` }} />}
    </div>
  );
}
