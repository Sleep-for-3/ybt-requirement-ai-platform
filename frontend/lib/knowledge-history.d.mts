export type HistoryMessage = { role: "user" | "assistant"; content: string };
export function appendHistory(history: HistoryMessage[], question: string, answer: string): HistoryMessage[];
