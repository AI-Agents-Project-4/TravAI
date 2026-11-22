"use client";

import Link from "next/link";
import { useEffect, useId, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { categoryLabel, formatMoney } from "@/lib/format";
import {
  addableOptions,
  addItem,
  indexOptions,
  isOverBudget,
  moveItem,
  planOptionIds,
  removeItem,
  runningTotal,
  toggleLock,
} from "@/lib/plan";
import type { DroppedItem, Option, Plan } from "@/lib/types";
import { Price } from "./Price";
import { card, primaryButton, secondaryButton } from "./styles";
import { WarningList } from "./WarningList";

type Loaded = { base: Plan; options: Option[] };

type Notice =
  | { kind: "redrafted"; dropped: DroppedItem[]; kept: number }
  | { kind: "saved" }
  | { kind: "error"; message: string };

const smallButton =
  "rounded-md border border-zinc-300 px-2 py-1 text-xs font-medium hover:bg-zinc-100 focus-visible:outline-2 focus-visible:outline-sky-600 disabled:opacity-60 dark:border-zinc-700 dark:hover:bg-zinc-800";

function errorMessage(e: unknown, fallback: string) {
  return e instanceof Error ? e.message : fallback;
}

/** Loads a plan and the options it can draw from, then hands off to the editor. */
export function PlanEditorPage({ planId }: { planId: string }) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const plan = await api.getPlan(planId);
        // GET /plans/{id} returns only the plan; prices and extra options
        // come from the trip's plans response.
        const plans = await api.getPlans(plan.trip_id);
        if (cancelled) return;
        setLoaded({ base: plan, options: plans.feasible ? plans.options : [] });
      } catch (e) {
        if (!cancelled) setError(errorMessage(e, "Couldn't load this plan."));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [planId]);

  if (error) {
    return (
      <section className={`${card} flex flex-col gap-3`} role="alert">
        <h1 className="text-xl font-semibold">Couldn&apos;t open this plan</h1>
        <p>{error}</p>
        <Link href="/" className={`${secondaryButton} self-start`}>
          Plan a new trip
        </Link>
      </section>
    );
  }
  if (!loaded) return <p className="text-zinc-500">Loading plan…</p>;
  return <PlanEditor initialPlan={loaded.base} options={loaded.options} />;
}

export function PlanEditor({ initialPlan, options }: { initialPlan: Plan; options: Option[] }) {
  const uid = useId();
  const index = useMemo(() => indexOptions(options), [options]);
  const [base, setBase] = useState(initialPlan);
  const [plan, setPlan] = useState(initialPlan);
  const [removedIds, setRemovedIds] = useState<string[]>([]);
  const [busy, setBusy] = useState<"redraft" | "save" | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [addDay, setAddDay] = useState<Record<string, number>>({});

  const total = runningTotal(base, plan, index);
  const over = isOverBudget(total.total, plan.budget);
  const edited = plan !== base;
  const addable = addableOptions(plan, options);
  const flight = plan.flight_option_id ? index.get(plan.flight_option_id) : undefined;
  const hotel = plan.hotel_option_id ? index.get(plan.hotel_option_id) : undefined;
  const lockedCount = plan.days.reduce((n, d) => n + d.items.filter((i) => i.locked).length, 0);

  function edit(next: Plan) {
    setPlan(next);
    setNotice(null);
  }

  function remove(day: number, i: number, optionId: string) {
    edit(removeItem(plan, day, i));
    setRemovedIds((ids) => (ids.includes(optionId) ? ids : [...ids, optionId]));
  }

  function add(optionId: string) {
    edit(addItem(plan, optionId, addDay[optionId] ?? plan.days[0]?.day ?? 1));
    setRemovedIds((ids) => ids.filter((id) => id !== optionId));
  }

  function reset() {
    setPlan(base);
    setRemovedIds([]);
    setNotice(null);
  }

  async function redraft() {
    setBusy("redraft");
    setNotice(null);
    try {
      const stillIn = new Set(planOptionIds(plan));
      const res = await api.redraftPlan(plan.id, {
        days: plan.days,
        removed_option_ids: removedIds.filter((id) => !stillIn.has(id)),
      });
      setBase(res.plan);
      setPlan(res.plan);
      setRemovedIds([]);
      setNotice({ kind: "redrafted", dropped: res.dropped_items, kept: lockedCount });
    } catch (e) {
      setNotice({ kind: "error", message: errorMessage(e, "The redraft failed. Your edits are still here.") });
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    setBusy("save");
    setNotice(null);
    try {
      // Save the totals the user saw, which never undercount the planner's.
      const saved = await api.savePlan({ ...plan, total: total.total, cost_breakdown: total.breakdown });
      setBase(saved);
      setPlan(saved);
      setRemovedIds([]);
      setNotice({ kind: "saved" });
    } catch (e) {
      setNotice({ kind: "error", message: errorMessage(e, "Couldn't save the plan.") });
    } finally {
      setBusy(null);
    }
  }

  const title = (optionId: string) => index.get(optionId)?.title ?? "Unknown item";

  return (
    <div className="flex flex-col gap-6 pb-20 lg:pb-0">
      {/* Phones: the full total panel is at the bottom, so keep the number in view. */}
      <div
        aria-hidden
        className="fixed inset-x-0 bottom-0 z-10 flex items-center justify-between gap-3 border-t border-zinc-200 bg-white/95 px-4 py-3 backdrop-blur lg:hidden dark:border-zinc-800 dark:bg-zinc-900/95"
      >
        <span className={`text-xl font-semibold tabular-nums ${over ? "text-red-600 dark:text-red-400" : ""}`}>
          {total.complete ? "" : "≥ "}
          {formatMoney(total.total)}
        </span>
        <span className={`text-sm ${over ? "text-red-600 dark:text-red-400" : "text-emerald-700 dark:text-emerald-400"}`}>
          {over
            ? `${formatMoney({ amount: total.total.amount - plan.budget.amount, currency: plan.budget.currency })} over budget`
            : `${formatMoney({ amount: plan.budget.amount - total.total.amount, currency: plan.budget.currency }, { round: "down" })} left`}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <Link
          href={`/trips/${encodeURIComponent(plan.trip_id)}`}
          className="text-sm text-sky-700 hover:underline dark:text-sky-400"
        >
          ← All three plans
        </Link>
        <h1 className="text-2xl font-semibold">{plan.title}</h1>
        <p className="text-zinc-600 dark:text-zinc-400">{plan.summary}</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="flex flex-col gap-6">
          <WarningList warnings={plan.warnings} />

          {(flight || hotel) && (
            <section className={`${card} flex flex-col gap-3`} aria-labelledby={`${uid}-travel`}>
              <h2 id={`${uid}-travel`} className="text-lg font-semibold">
                Getting there and staying
              </h2>
              <ul className="flex flex-col gap-3">
                {[flight, hotel].filter(Boolean).map((o) => (
                  <li key={o!.id} className="flex flex-col">
                    <span className="font-medium">{o!.title}</span>
                    {o!.description && <span className="text-sm text-zinc-600 dark:text-zinc-400">{o!.description}</span>}
                    <Price option={o!} />
                  </li>
                ))}
              </ul>
            </section>
          )}

          {plan.days.map((day) => (
            <section key={day.day} className={`${card} flex flex-col gap-3`} aria-labelledby={`${uid}-day-${day.day}`}>
              <h2 id={`${uid}-day-${day.day}`} className="text-lg font-semibold">
                Day {day.day}
                {day.date && <span className="ml-2 text-sm font-normal text-zinc-500">{day.date}</span>}
              </h2>
              {day.items.length === 0 && <p className="text-sm text-zinc-500">Nothing planned yet.</p>}
              <ol className="flex flex-col divide-y divide-zinc-200 dark:divide-zinc-800">
                {day.items.map((item, i) => {
                  const option = index.get(item.option_id);
                  const name = title(item.option_id);
                  return (
                    <li key={`${item.option_id}-${i}`} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex flex-col gap-0.5">
                        <span className="font-medium">
                          {item.start_time && (
                            <span className="mr-2 text-sm tabular-nums text-zinc-500">
                              {item.start_time}
                              {item.end_time && `–${item.end_time}`}
                            </span>
                          )}
                          {name}
                          {item.locked && (
                            <span className="ml-2 rounded bg-sky-100 px-1.5 py-0.5 text-xs font-medium text-sky-900 dark:bg-sky-900/40 dark:text-sky-200">
                              kept
                            </span>
                          )}
                        </span>
                        {option ? (
                          <Price option={option} />
                        ) : (
                          <span className="text-sm text-red-600">No price found for this item</span>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          className={smallButton}
                          aria-pressed={item.locked}
                          aria-label={`Keep ${name} in a redraft`}
                          onClick={() => edit(toggleLock(plan, day.day, i))}
                        >
                          {item.locked ? "Kept" : "Keep"}
                        </button>
                        {plan.days.length > 1 && (
                          <label className="flex items-center gap-1 text-xs">
                            <span className="sr-only">Move {name} to</span>
                            <select
                              className="rounded-md border border-zinc-300 bg-white px-1.5 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
                              value={day.day}
                              onChange={(e) => edit(moveItem(plan, day.day, i, Number(e.target.value)))}
                            >
                              {plan.days.map((d) => (
                                <option key={d.day} value={d.day}>
                                  {d.day === day.day ? `Day ${d.day}` : `Move to day ${d.day}`}
                                </option>
                              ))}
                            </select>
                          </label>
                        )}
                        <button
                          type="button"
                          className={smallButton}
                          aria-label={`Remove ${name}`}
                          onClick={() => remove(day.day, i, item.option_id)}
                        >
                          Remove
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </section>
          ))}

          <section className={`${card} flex flex-col gap-3`} aria-labelledby={`${uid}-more`}>
            <h2 id={`${uid}-more`} className="text-lg font-semibold">
              Other options we found
            </h2>
            {addable.length === 0 ? (
              <p className="text-sm text-zinc-500">Everything we found is already in this plan.</p>
            ) : (
              <ul className="flex flex-col divide-y divide-zinc-200 dark:divide-zinc-800">
                {addable.map((o) => (
                  <li key={o.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium">{o.title}</span>
                      <Price option={o} />
                    </div>
                    <div className="flex items-center gap-2">
                      {plan.days.length > 1 && (
                        <label className="flex items-center gap-1 text-xs">
                          <span className="sr-only">Day to add {o.title} to</span>
                          <select
                            className="rounded-md border border-zinc-300 bg-white px-1.5 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
                            value={addDay[o.id] ?? plan.days[0].day}
                            onChange={(e) => setAddDay((m) => ({ ...m, [o.id]: Number(e.target.value) }))}
                          >
                            {plan.days.map((d) => (
                              <option key={d.day} value={d.day}>
                                Day {d.day}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                      <button type="button" className={smallButton} aria-label={`Add ${o.title}`} onClick={() => add(o.id)}>
                        Add
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <aside className="lg:sticky lg:top-6 lg:self-start" aria-labelledby={`${uid}-total`}>
          <div className={`${card} flex flex-col gap-4`}>
            <div role="status" aria-live="polite">
              <h2 id={`${uid}-total`} className="text-sm font-medium text-zinc-500">
                Running total
              </h2>
              <p className={`text-3xl font-semibold tabular-nums ${over ? "text-red-600 dark:text-red-400" : ""}`}>
                {total.complete ? "" : "At least "}
                {formatMoney(total.total)}
              </p>
              <p className={`text-sm ${over ? "text-red-600 dark:text-red-400" : "text-emerald-700 dark:text-emerald-400"}`}>
                {over
                  ? `${formatMoney({ amount: total.total.amount - plan.budget.amount, currency: plan.budget.currency })} over your ${formatMoney(plan.budget)} budget`
                  : `${formatMoney({ amount: plan.budget.amount - total.total.amount, currency: plan.budget.currency }, { round: "down" })} left of your ${formatMoney(plan.budget)} budget`}
              </p>
              {!total.complete && (
                <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
                  Some prices are missing or in another currency, so the real total is higher.
                </p>
              )}
            </div>

            <dl className="flex flex-col gap-1 text-sm">
              {total.breakdown.map((line) => (
                <div key={line.category} className="flex justify-between gap-4">
                  <dt className="text-zinc-600 dark:text-zinc-400">{categoryLabel(line.category)}</dt>
                  <dd className="tabular-nums">{formatMoney(line.total)}</dd>
                </div>
              ))}
            </dl>

            <div className="flex flex-col gap-2">
              <button type="button" className={primaryButton} onClick={redraft} disabled={busy !== null}>
                {busy === "redraft" ? "Redrafting…" : "Redraft around my changes"}
              </button>
              <button type="button" className={secondaryButton} onClick={save} disabled={busy !== null}>
                {busy === "save" ? "Saving…" : plan.saved && !edited ? "Saved" : "Save plan"}
              </button>
              {edited && (
                <button type="button" className="text-sm text-zinc-600 underline dark:text-zinc-400" onClick={reset}>
                  Undo my changes
                </button>
              )}
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Items you add or move are kept in a redraft. Use “Keep” to hold anything else in place.
              </p>
            </div>

            {notice && <NoticeBox notice={notice} titleOf={title} />}
          </div>
        </aside>
      </div>
    </div>
  );
}

function NoticeBox({ notice, titleOf }: { notice: Notice; titleOf: (id: string) => string }) {
  if (notice.kind === "error") {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        {notice.message}
      </p>
    );
  }
  if (notice.kind === "saved") {
    return (
      <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
        Plan saved. You can come back to this page any time.
      </p>
    );
  }
  return (
    <div role="status" className="flex flex-col gap-2 text-sm">
      <p className="font-medium">
        Redrafted. {notice.kept > 0 ? `Your ${notice.kept} kept item${notice.kept === 1 ? " was" : "s were"} kept.` : ""}
      </p>
      {notice.dropped.length > 0 ? (
        <>
          <p>To stay on budget, the planner dropped:</p>
          <ul className="list-disc pl-5">
            {notice.dropped.map((d) => (
              <li key={d.option_id}>
                <span className="font-medium">{titleOf(d.option_id)}</span>: {d.reason}
              </li>
            ))}
          </ul>
          <p className="text-zinc-500">You can add them back from “Other options we found”.</p>
        </>
      ) : (
        <p>Nothing was dropped.</p>
      )}
    </div>
  );
}
