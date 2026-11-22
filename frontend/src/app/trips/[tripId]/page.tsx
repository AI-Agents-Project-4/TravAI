import type { Metadata } from "next";
import { Suspense } from "react";
import { TripView } from "@/components/TripView";

export const metadata: Metadata = { title: "Your trip · TravAI" };

async function Trip({ params }: { params: Promise<{ tripId: string }> }) {
  const { tripId } = await params;
  return <TripView tripId={tripId} />;
}

export default function TripPage({ params }: PageProps<"/trips/[tripId]">) {
  return (
    <Suspense fallback={<p className="text-zinc-500">Loading trip…</p>}>
      <Trip params={params} />
    </Suspense>
  );
}
