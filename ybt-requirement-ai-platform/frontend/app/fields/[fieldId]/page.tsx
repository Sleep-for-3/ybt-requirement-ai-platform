import { redirect } from "next/navigation";

export default function FieldPage({ params }: { params: { fieldId: string } }) {
  redirect(`/fields/${params.fieldId}/scenarios`);
}
