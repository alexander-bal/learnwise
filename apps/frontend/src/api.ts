export type PromptStatus = "active" | "superseded" | "candidate" | "rejected" | "abandoned";

export interface PromptVersion {
  id: number;
  parent_id: number | null;
  status: PromptStatus;
  change_reason: string;
  content: string;
  created_at: string;
}

export async function fetchPrompts(signal?: AbortSignal): Promise<PromptVersion[]> {
  const response = await fetch("/api/prompts", { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`The server answered ${response.status}.`);
  }
  return (await response.json()) as PromptVersion[];
}
