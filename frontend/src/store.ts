import { create } from 'zustand'
import type { AgentEvent, CompletePayload, HITLPayload, TokenUsage } from './types'

interface AgentIQStore {
  currentRunId: string | null
  agentEvents: AgentEvent[]
  hitlPayload: HITLPayload | null
  finalState: CompletePayload['final_state'] | null
  tokenUsage: TokenUsage

  setRunId: (runId: string) => void
  appendEvent: (event: AgentEvent) => void
  setHITL: (payload: HITLPayload | null) => void
  setFinal: (payload: CompletePayload) => void
  resetStore: () => void
}

const emptyUsage: TokenUsage = {
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  cost_usd: 0,
}

export const useStore = create<AgentIQStore>((set) => ({
  currentRunId: null,
  agentEvents: [],
  hitlPayload: null,
  finalState: null,
  tokenUsage: { ...emptyUsage },

  setRunId: (runId) => set({ currentRunId: runId }),

  appendEvent: (event) =>
    set((state) => {
      // Keep the live cost badge in sync with whatever the latest event reports.
      const usage = event.token_usage
      const tokenUsage: TokenUsage = usage
        ? {
            input_tokens: usage.input_tokens ?? state.tokenUsage.input_tokens,
            output_tokens: usage.output_tokens ?? state.tokenUsage.output_tokens,
            total_tokens: usage.total_tokens ?? state.tokenUsage.total_tokens,
            cost_usd: usage.cost_usd ?? state.tokenUsage.cost_usd,
          }
        : state.tokenUsage
      return { agentEvents: [...state.agentEvents, event], tokenUsage }
    }),

  setHITL: (payload) => set({ hitlPayload: payload }),

  setFinal: (payload) => set({ finalState: payload.final_state }),

  resetStore: () =>
    set({
      currentRunId: null,
      agentEvents: [],
      hitlPayload: null,
      finalState: null,
      tokenUsage: { ...emptyUsage },
    }),
}))
