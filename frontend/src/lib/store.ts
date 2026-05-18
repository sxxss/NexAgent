import { create } from "zustand";
import type { ReasoningMode } from "@/lib/api";

interface WorkspaceState {
  selectedAgentId: string;
  selectedModelName: string;
  reasoningMode: ReasoningMode;
  reasoningBudget: number;
  setSelectedAgentId: (value: string) => void;
  setSelectedModelName: (value: string) => void;
  setReasoningMode: (value: ReasoningMode) => void;
  setReasoningBudget: (value: number) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  selectedAgentId: "chatbot",
  selectedModelName: "",
  reasoningMode: "balanced",
  reasoningBudget: 8000,
  setSelectedAgentId: (selectedAgentId) => set({ selectedAgentId }),
  setSelectedModelName: (selectedModelName) => set({ selectedModelName }),
  setReasoningMode: (reasoningMode) => set({ reasoningMode }),
  setReasoningBudget: (reasoningBudget) => set({ reasoningBudget }),
}));
