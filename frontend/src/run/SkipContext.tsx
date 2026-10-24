import { createContext, useContext } from "react";
export type SkipItem = {
  graph: string;
  card: string;
  name: string;
  scope?: string;
  reasons: { reason: string; source: string }[];
};
export type SkipPlan = {
  token: string;
  revision: string;
  run_id: string | null;
  marks: { graph: string; card: string }[];
  affected: SkipItem[];
  children: SkipItem[];
  continuations: { graph: string; card: string; next: string }[];
  blockers: string[];
  consumed: string[];
};
export const SkipContext = createContext<{
  plan: SkipPlan | null;
  preview: SkipPlan | null;
}>({ plan: null, preview: null });
export function useSkipCard(graph: string, card: string) {
  const { plan, preview } = useContext(SkipContext);
  return {
    marked: plan?.affected.find((x) => x.graph === graph && x.card === card),
    previewing: !!preview?.affected.some(
      (x) => x.graph === graph && x.card === card,
    ),
  };
}
