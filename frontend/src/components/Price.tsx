import { formatAge, formatMoney, formatTimestamp, safeHttpUrl, sourceLabel } from "@/lib/format";
import type { Option } from "@/lib/types";

/**
 * A price with everything product rule 2 asks for: the amount in its
 * currency, an "estimate" label when there was no exact quote, the source
 * link and how old the price is.
 */
export function Price({ option }: { option: Option }) {
  const href = safeHttpUrl(option.source_url);
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
      <span className="font-semibold tabular-nums">{formatMoney(option.price)}</span>
      {option.price_is_estimate && (
        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">
          estimate
        </span>
      )}
      <span className="text-xs text-zinc-500 dark:text-zinc-400">
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="underline decoration-zinc-300 underline-offset-2 hover:text-zinc-900 dark:decoration-zinc-600 dark:hover:text-zinc-100"
          >
            {sourceLabel(href)}
            <span className="sr-only"> (source for {option.title}, opens in a new tab)</span>
          </a>
        ) : (
          <span title={option.source_url}>source link unavailable</span>
        )}
        {" · "}
        <time dateTime={option.fetched_at} title={formatTimestamp(option.fetched_at)} suppressHydrationWarning>
          fetched {formatAge(option.fetched_at)}
        </time>
      </span>
    </span>
  );
}
