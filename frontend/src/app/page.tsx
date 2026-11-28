import { TripForm } from "@/components/TripForm";

export default function Home() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-8">
      <div className="flex flex-col gap-3 text-center">
        <h1 className="text-4xl font-semibold tracking-tight">TravAI</h1>
        <p className="text-lg text-zinc-600 dark:text-zinc-400">
          Tell us where you want to go and what you can spend. We&apos;ll research real prices and give you three
          itineraries that fit your budget, or tell you honestly if it can&apos;t be done.
        </p>
      </div>
      <TripForm />
    </div>
  );
}
