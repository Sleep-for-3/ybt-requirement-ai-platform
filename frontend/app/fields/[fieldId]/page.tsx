import { redirect } from "next/navigation";

// Next 15 hands server components a promise; awaiting it also works on Next 14.
export default async function FieldPage({ params }: { params: Promise<{ fieldId: string }> }) {
  const { fieldId } = await params;
  redirect(`/fields/${fieldId}/scenarios`);
}
