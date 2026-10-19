export type BindingTodoItem = {
  skill_key: string;
  display_name: string;
  reason: "no_binding" | "no_published_version";
  available: boolean;
  version_no: number | null;
  detail: string;
};

export type BindingTodoView = {
  count: number;
  actionable: number;
  items: BindingTodoItem[];
  message: string;
};

export function bindingTodoView(todos: unknown): BindingTodoView | null;
