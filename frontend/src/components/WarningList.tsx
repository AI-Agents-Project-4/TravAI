import { safeHttpUrl } from "@/lib/format";
import type { Warning, WarningKind } from "@/lib/types";

const LABELS: Record<WarningKind, string> = {
  safety: "Safety",
  stale_data: "Possibly out of date",
  estimate: "Estimate",
  over_budget: "Over budget",
};

const STYLES: Record<WarningKind, string> = {
  safety: "border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950/50 dark:text-red-100",
  over_budget: "border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950/50 dark:text-red-100",
  stale_data: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-100",
  estimate: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-100",
};

/** Same message from several plans shows once. */
export function uniqueWarnings(warnings: Warning[]): Warning[] {
  const seen = new Set<string>();
  return warnings.filter((w) => {
    const key = `${w.kind}:${w.message}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function WarningList({ warnings }: { warnings: Warning[] }) {
  if (warnings.length === 0) return null;
  return (
    <ul className="flex flex-col gap-2">
      {warnings.map((w) => {
        const href = w.source_url ? safeHttpUrl(w.source_url) : null;
        return (
          <li key={`${w.kind}:${w.message}`} className={`rounded-lg border px-4 py-3 text-sm ${STYLES[w.kind]}`}>
            <strong className="font-semibold">{LABELS[w.kind]}: </strong>
            {w.message}
            {href && (
              <>
                {" "}
                <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="underline">
                  Source
                </a>
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}
