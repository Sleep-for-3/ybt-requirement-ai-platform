export type CockpitErrorState = { kind: "error" | "forbidden"; title: string; description: string };
export function cockpitErrorState(error: { status?: number; errorCode?: string | null; message?: string } | null | undefined): CockpitErrorState;
