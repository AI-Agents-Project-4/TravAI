"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useTripProgress } from "@/lib/api/use-trip-progress";
import { categoryLabel, formatMoney, sortBreakdown } from "@/lib/format";
import { indexOptions } from "@/lib/plan";
import type { Money, Option, Plan, PlansResponse, TripProgress } from "@/lib/types";
import { Price } from "./Price";
import { card, primaryButton, secondaryButton } from "./styles";
import { uniqueWarnings, WarningList } from "./WarningList";

export function ProgressSteps({
  progress,
  stalled = false,
  connectionError = null,
}: {
  progress: TripProgress | null;
  stalled?: boolean;
  connectionError?: string | null;
}) {
  const steps = progress?.steps ?? [];
  const heading =
    progress?.status === "planning" ? "Building your itineraries…" : "Researching real prices…";
  return (
    <section className={`${card} flex flex-col gap-4`} aria-labelledby="progress-heading">
      <div className="flex items-center gap-3">
        <span
          aria-hidden
          className="h-4 w-4 animate-spin rounded-full border-2 border-sky-600 border-t-transparent"
        />
        <h1 id="progress-heading" className="text-xl font-semibold">
          {heading}
        </h1>
      </div>
      <ol aria-live="polite" className="flex flex-col gap-2 text-sm">
        {steps.length === 0 && <li className="text-zinc-500">Starting…</li>}
        {steps.map((step, i) => (
          <li key={`${step.at}-${i}`} className="flex gap-2">
            <span aria-hidden className={i === steps.length - 1 ? "text-sky-600" : "text-emerald-600"}>
              {i === steps.length - 1 ? "•" : "✓"}
            </span>
            {step.message}
          </li>
        ))}
      </ol>
      {connectionError && (
        <p className="text-sm text-amber-700 dark:text-amber-400">
          Trouble reaching the server ({connectionError}). Retrying…
        </p>
      )}
      {stalled ? (
        <div role="status" className="flex flex-col gap-2 text-sm text-zinc-700 dark:text-zinc-300">
          <p>This is taking longer than usual. We&apos;ll keep checking.</p>
          <Link href="/" className="self-start text-sky-700 underline dark:text-sky-400">
            Start over with a different trip
          </Link>
        </div>
      ) : (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          This can take a minute. Every price we find comes with a link to where we found it.
        </p>
      )}
    </section>
  );
}

export function TimedOut({ onRetry }: { onRetry: () => void }) {
  return (
    <section className={`${card} flex flex-col gap-3`} role="alert">
      <h1 className="text-xl font-semibold">Research has stopped making progress</h1>
      <p className="text-zinc-700 dark:text-zinc-300">
        Nothing new has come in for 10 minutes, so we stopped checking. You can check again or plan a different trip.
      </p>
      <div className="flex flex-wrap gap-3">
        <button type="button" className={primaryButton} onClick={onRetry}>
          Check again
        </button>
        <Link href="/" className={secondaryButton}>
          Start over
        </Link>
      </div>
    </section>
  );
}

export function Infeasible({
  reason,
  minCost,
  budget,
}: {
  reason: string;
  minCost: Money;
  budget?: Money;
}) {
  return (
    <section className={`${card} flex flex-col gap-4`} aria-labelledby="infeasible-heading">
      <h1 id="infeasible-heading" className="text-2xl font-semibold">
        This trip doesn&apos;t fit the budget
      </h1>
      <p className="text-zinc-700 dark:text-zinc-300">{reason}</p>
      <dl className="grid grid-cols-2 gap-4 sm:max-w-sm">
        <div>
          <dt className="text-sm text-zinc-500">Minimum estimated cost</dt>
          <dd className="text-2xl font-semibold tabular-nums">{formatMoney(minCost)}</dd>
        </div>
        {budget && (
          <div>
            <dt className="text-sm text-zinc-500">Your budget</dt>
            <dd className="text-2xl font-semibold tabular-nums">{formatMoney(budget)}</dd>
          </div>
        )}
      </dl>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        We&apos;d rather tell you now than show a plan that falls apart once you book. Try fewer days, a closer
        destination or a bigger budget.
      </p>
      <Link href="/" className={`${primaryButton} self-start`}>
        Change the trip
      </Link>
    </section>
  );
}

function PlanCard({ plan, options }: { plan: Plan; options: ReadonlyMap<string, Option> }) {
  const flight = plan.flight_option_id ? options.get(plan.flight_option_id) : undefined;
  const hotel = plan.hotel_option_id ? options.get(plan.hotel_option_id) : undefined;
  const over = plan.total.amount > plan.budget.amount;
  const difference = { amount: Math.abs(plan.budget.amount - plan.total.amount), currency: plan.total.currency };
  const itemCount = plan.days.reduce((n, d) => n + d.items.length, 0);
  return (
    <article className={`${card} flex flex-col gap-4`} aria-labelledby={`plan-${plan.id}`}>
      <header className="flex flex-col gap-1">
        <h2 id={`plan-${plan.id}`} className="text-lg font-semibold">
          {plan.title}
        </h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">{plan.summary}</p>
      </header>

      <div>
        <p className="text-3xl font-semibold tabular-nums">{formatMoney(plan.total)}</p>
        <p className={`text-sm ${over ? "text-red-600 dark:text-red-400" : "text-emerald-700 dark:text-emerald-400"}`}>
          {over ? `${formatMoney(difference)} over` : `${formatMoney(difference, { round: "down" })} under`} your{" "}
          {formatMoney(plan.budget)} budget
        </p>
      </div>

      <dl className="flex flex-col gap-1 text-sm">
        {sortBreakdown(plan.cost_breakdown).map((line) => (
          <div key={line.category} className="flex justify-between gap-4">
            <dt className="text-zinc-600 dark:text-zinc-400">{categoryLabel(line.category)}</dt>
            <dd className="tabular-nums">{formatMoney(line.total)}</dd>
          </div>
        ))}
      </dl>

      {(flight || hotel) && (
        <ul className="flex flex-col gap-2 border-t border-zinc-200 pt-3 text-sm dark:border-zinc-800">
          {[flight, hotel].filter(Boolean).map((o) => (
            <li key={o!.id} className="flex flex-col">
              <span>{o!.title}</span>
              <Price option={o!} />
            </li>
          ))}
        </ul>
      )}

      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        {plan.days.length} day{plan.days.length === 1 ? "" : "s"}, {itemCount} planned stop{itemCount === 1 ? "" : "s"}
      </p>

      <Link
        href={`/plans/${encodeURIComponent(plan.id)}`}
        aria-label={`View and edit ${plan.title}`}
        className={`${secondaryButton} mt-auto`}
      >
        View and edit
      </Link>
    </article>
  );
}

export function PlanComparison({ plans, options }: { plans: Plan[]; options: Option[] }) {
  const index = indexOptions(options);
  const warnings = uniqueWarnings(plans.flatMap((p) => p.warnings).filter((w) => w.kind !== "over_budget"));
  return (
    <section className="flex flex-col gap-6" aria-labelledby="plans-heading">
      <div className="flex flex-col gap-1">
        <h1 id="plans-heading" className="text-2xl font-semibold">
          Three ways to do this trip
        </h1>
        <p className="text-zinc-600 dark:text-zinc-400">Pick one to see the day-by-day plan and make it yours.</p>
      </div>
      <WarningList warnings={warnings} />
      <div className="grid gap-4 md:grid-cols-3">
        {plans.map((plan) => (
          <PlanCard key={plan.id} plan={plan} options={index} />
        ))}
      </div>
    </section>
  );
}

export function TripView({ tripId }: { tripId: string }) {
  const { progress, error, stalled, timedOut, retry } = useTripProgress(tripId);
  const [result, setResult] = useState<PlansResponse | null>(null);
  const [plansError, setPlansError] = useState<string | null>(null);
  const done = progress?.status === "done";

  useEffect(() => {
    if (!done) return;
    let cancelled = false;
    api.getPlans(tripId).then(
      (r) => !cancelled && setResult(r),
      (e: unknown) => !cancelled && setPlansError(e instanceof Error ? e.message : "Couldn't load the plans."),
    );
    return () => {
      cancelled = true;
    };
  }, [done, tripId]);

  const failure = plansError ?? (progress?.status === "failed" ? "Research failed for this trip." : null);
  if (failure || (error && !progress)) {
    return (
      <section className={`${card} flex flex-col gap-3`} role="alert">
        <h1 className="text-xl font-semibold">Something went wrong</h1>
        <p className="text-zinc-700 dark:text-zinc-300">{failure ?? error}</p>
        <Link href="/" className={`${secondaryButton} self-start`}>
          Start over
        </Link>
      </section>
    );
  }

  if (!result && timedOut) return <TimedOut onRetry={retry} />;
  if (!result) return <ProgressSteps progress={progress} stalled={stalled} connectionError={error} />;

  if (!result.feasible) {
    return <Infeasible reason={result.reason} minCost={result.min_estimated_cost} />;
  }
  return <PlanComparison plans={result.plans} options={result.options} />;
}
