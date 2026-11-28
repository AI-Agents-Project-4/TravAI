import type { Metadata } from "next";
import { Suspense } from "react";
import { PlanEditorPage } from "@/components/PlanEditor";

export const metadata: Metadata = { title: "Your plan · TravAI" };

async function Plan({ params }: { params: Promise<{ planId: string }> }) {
  const { planId } = await params;
  return <PlanEditorPage planId={planId} />;
}

export default function PlanPage({ params }: PageProps<"/plans/[planId]">) {
  return (
    <Suspense fallback={<p className="text-zinc-500">Loading plan…</p>}>
      <Plan params={params} />
    </Suspense>
  );
}
