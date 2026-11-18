export function appendHistory(history, question, answer) {
  const next = [...history, { role: "user", content: question.trim() },
    { role: "assistant", content: answer.trim() }];
  while (next.length > 12 || next.reduce((size, row) => size + row.content.length, 0) > 12000) {
    next.splice(0, 2);
  }
  return next;
}
