// TypeScript interfaces mirroring the backend Pydantic models / state.

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
}

export interface DraftOutput {
  subject: string
  body: string
  reasoning?: string
  estimated_open_rate?: string
}

export interface EvalOutput {
  score: number
  personalisation_score?: number
  clarity_score?: number
  relevance_score?: number
  feedback: string
  passed: boolean
}

export interface AnalysisOutput {
  fit_score: number
  fit_reasoning?: string
  personalization_hooks?: string[]
  recommended_tone?: string
  red_flags?: string[]
}

export interface AgentIQState {
  run_id: string
  lead: Record<string, unknown>
  research_output: Record<string, unknown>
  analysis_output: Partial<AnalysisOutput>
  draft_output: Partial<DraftOutput>
  eval_output: Partial<EvalOutput>
  hitl_decision: string
  hitl_feedback: string
  error: string
  token_usage: Partial<TokenUsage>
}

export interface RunRecord {
  id: string
  created_at: string
  lead: Record<string, unknown>
  status: string
  token_usage: Partial<TokenUsage>
}

export interface HITLPayload {
  run_id: string
  draft: Partial<DraftOutput>
  eval_feedback: string
}

// A single live event streamed from the backend over SSE.
export interface AgentEvent {
  node: string
  status: string
  partial_output: Record<string, unknown>
  token_usage?: Partial<TokenUsage>
  timestamp: string
}

// Payload of the terminal "complete" SSE event.
export interface CompletePayload {
  run_id: string
  final_state: {
    analysis_output?: Partial<AnalysisOutput>
    draft_output?: Partial<DraftOutput>
    eval_output?: Partial<EvalOutput>
    error?: string
  }
}

export type Lead = {
  company_name: string
  website: string
  icp_notes: string
  recipient_email: string
}

export const PIPELINE_NODES = ['researcher', 'analyst', 'drafter', 'evaluator'] as const
export type PipelineNode = (typeof PIPELINE_NODES)[number]
export type StepStatus = 'pending' | 'active' | 'complete'
