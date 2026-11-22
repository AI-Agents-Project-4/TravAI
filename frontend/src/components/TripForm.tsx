"use client";

import { useRouter } from "next/navigation";
import { useId, useLayoutEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import {
  CURRENCIES,
  EMPTY_TRIP_FORM,
  LIMITS,
  parseTripForm,
  type TripFormErrors,
  type TripFormValues,
} from "@/lib/trip-form";
import type { Warning } from "@/lib/types";
import { input, primaryButton, secondaryButton } from "./styles";
import { WarningList } from "./WarningList";

function Field({
  id,
  label,
  hint,
  error,
  children,
  className = "",
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label htmlFor={id} className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-zinc-500 dark:text-zinc-400">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}

export function TripForm() {
  const router = useRouter();
  const uid = useId();
  const [values, setValues] = useState<TripFormValues>(EMPTY_TRIP_FORM);
  const [errors, setErrors] = useState<TripFormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ tripId: string; warnings: Warning[] } | null>(null);

  // cacheComponents keeps this page mounted (hidden) after we navigate to the
  // trip. Keep what the user typed, so "Change the trip" brings it back, but
  // reset the submit state and the safety panel so they aren't stale on return.
  useLayoutEffect(
    () => () => {
      setSubmitting(false);
      setPending(null);
      setServerError(null);
    },
    [],
  );

  const fieldId = (name: keyof TripFormValues) => `${uid}-${name}`;
  const describedBy = (name: keyof TripFormValues, hasHint = false) =>
    errors[name] ? `${fieldId(name)}-error` : hasHint ? `${fieldId(name)}-hint` : undefined;

  function set<K extends keyof TripFormValues>(name: K, value: TripFormValues[K]) {
    setValues((v) => ({ ...v, [name]: value }));
    if (errors[name]) setErrors((e) => ({ ...e, [name]: undefined }));
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setServerError(null);
    const parsed = parseTripForm(values);
    if (!parsed.ok) {
      setErrors(parsed.errors);
      const first = Object.keys(parsed.errors)[0] as keyof TripFormValues;
      document.getElementById(fieldId(first))?.focus();
      return;
    }
    setSubmitting(true);
    try {
      const { trip_id, warnings } = await api.createTrip(parsed.request);
      if (warnings.some((w) => w.kind === "safety")) {
        // Product rule 4: warn first, then let the user decide.
        setPending({ tripId: trip_id, warnings });
        setSubmitting(false);
        return;
      }
      router.push(`/trips/${encodeURIComponent(trip_id)}`);
    } catch (e) {
      setServerError(e instanceof Error ? e.message : "Something went wrong. Try again.");
      setSubmitting(false);
    }
  }

  async function proceed() {
    if (!pending) return;
    setSubmitting(true);
    setServerError(null);
    try {
      await api.proceedTrip(pending.tripId);
      router.push(`/trips/${encodeURIComponent(pending.tripId)}`);
    } catch (e) {
      setServerError(e instanceof Error ? e.message : "Something went wrong. Try again.");
      setSubmitting(false);
    }
  }

  if (pending) {
    return (
      <section
        aria-labelledby={`${uid}-safety`}
        className="flex flex-col gap-4 rounded-2xl border border-red-200 bg-white p-6 shadow-sm dark:border-red-900 dark:bg-zinc-900"
      >
        <h2 id={`${uid}-safety`} className="text-xl font-semibold">
          Before you plan this trip
        </h2>
        <WarningList warnings={pending.warnings} />
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          You can still go ahead. TravAI will plan it like any other trip, assuming the map and price data it finds is
          correct.
        </p>
        {serverError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {serverError}
          </p>
        )}
        <div className="flex flex-wrap gap-3">
          <button type="button" className={primaryButton} onClick={proceed} disabled={submitting}>
            {submitting ? "Starting…" : "Proceed anyway"}
          </button>
          <button type="button" className={secondaryButton} onClick={() => setPending(null)} disabled={submitting}>
            Change my trip
          </button>
        </div>
      </section>
    );
  }

  return (
    <form
      noValidate
      onSubmit={onSubmit}
      aria-label="Plan a trip"
      className="flex flex-col gap-5 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
    >
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium text-zinc-800 dark:text-zinc-200">How are you getting there?</legend>
        <div className="flex gap-4">
          {(["fly", "drive"] as const).map((mode) => (
            <label key={mode} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="transport_mode"
                value={mode}
                checked={values.transport_mode === mode}
                onChange={() => set("transport_mode", mode)}
                className="h-4 w-4 accent-sky-600"
              />
              {mode === "fly" ? "Fly" : "Drive"}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id={fieldId("origin")}
          label={values.transport_mode === "fly" ? "Flying from" : "Driving from"}
          hint={values.transport_mode === "fly" ? "Airport code or city, like DEN" : "City or town"}
          error={errors.origin}
        >
          <input
            id={fieldId("origin")}
            className={input}
            value={values.origin}
            onChange={(e) => set("origin", e.target.value)}
            aria-invalid={!!errors.origin}
            aria-describedby={describedBy("origin", true)}
            autoComplete="off"
          />
        </Field>
        <Field id={fieldId("destination")} label="Destination" hint="City, region or country" error={errors.destination}>
          <input
            id={fieldId("destination")}
            className={input}
            value={values.destination}
            onChange={(e) => set("destination", e.target.value)}
            aria-invalid={!!errors.destination}
            aria-describedby={describedBy("destination", true)}
            autoComplete="off"
          />
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field id={fieldId("start_date")} label="Start date" hint="Optional. Blank means flexible." error={errors.start_date}>
          <input
            id={fieldId("start_date")}
            type="date"
            className={input}
            value={values.start_date}
            onChange={(e) => set("start_date", e.target.value)}
            aria-invalid={!!errors.start_date}
            aria-describedby={describedBy("start_date", true)}
          />
        </Field>
        <Field id={fieldId("duration_days")} label="Days" error={errors.duration_days}>
          <input
            id={fieldId("duration_days")}
            type="number"
            inputMode="numeric"
            min={1}
            max={LIMITS.maxDays}
            className={input}
            value={values.duration_days}
            onChange={(e) => set("duration_days", e.target.value)}
            aria-invalid={!!errors.duration_days}
            aria-describedby={describedBy("duration_days")}
          />
        </Field>
        <Field id={fieldId("travelers")} label="Travelers" error={errors.travelers}>
          <input
            id={fieldId("travelers")}
            type="number"
            inputMode="numeric"
            min={1}
            max={LIMITS.maxTravelers}
            className={input}
            value={values.travelers}
            onChange={(e) => set("travelers", e.target.value)}
            aria-invalid={!!errors.travelers}
            aria-describedby={describedBy("travelers")}
          />
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
        <Field
          id={fieldId("budget")}
          label="Total budget"
          hint="For everyone, including flights, hotel, food and getting around"
          error={errors.budget}
        >
          <input
            id={fieldId("budget")}
            inputMode="decimal"
            className={input}
            placeholder="5000"
            value={values.budget}
            onChange={(e) => set("budget", e.target.value)}
            aria-invalid={!!errors.budget}
            aria-describedby={describedBy("budget", true)}
          />
        </Field>
        <Field id={fieldId("currency")} label="Currency">
          <select
            id={fieldId("currency")}
            className={input}
            value={values.currency}
            onChange={(e) => set("currency", e.target.value)}
          >
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field
        id={fieldId("end_destination")}
        label="Ending somewhere else? (optional)"
        hint="For multi-stop trips, like starting in Paris and ending in Rome"
      >
        <input
          id={fieldId("end_destination")}
          className={input}
          value={values.end_destination}
          onChange={(e) => set("end_destination", e.target.value)}
          aria-describedby={describedBy("end_destination", true)}
          autoComplete="off"
        />
      </Field>

      {serverError && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {serverError}
        </p>
      )}

      <button type="submit" className={`${primaryButton} self-start`} disabled={submitting}>
        {submitting ? "Starting…" : "Plan my trip"}
      </button>
    </form>
  );
}
