export const CONFIG_AGENT_URL = (import.meta.env.VITE_CONFIG_AGENT_URL as string | undefined) ?? 'http://localhost:8001';

export interface ConfigAgentChatResponse {
  status: 'clarify' | 'done' | 'awaiting_review' | 'completed' | 'running' | 'rejected' | 'error';
  question?: string;
  final_output?: object;
  output_file?: string;
  session_id: string;
  run_id?: string;
  message?: string;
}

export interface ConfigAgentGenerateResponse {
  final_output: object;
  output_file: string;
}

export const generateConfig = async (input: string): Promise<ConfigAgentGenerateResponse> => {
  const res = await fetch(`${CONFIG_AGENT_URL}/generate-config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input }),
  });
  if (!res.ok) throw new Error(`Config agent error: ${res.status}`);
  return res.json();
};

export interface ConfigListItem {
  filename: string;
  url: string;
  size: number;
}

export interface SessionSummary {
  session_id: string;
  title: string;
  status: 'active' | 'clarifying' | 'done' | 'error';
  created_at: string;
  updated_at: string;
  message_count: number;
  has_output: boolean;
}

export interface SessionMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface SessionDetail extends SessionSummary {
  messages: SessionMessage[];
  final_output: object | null;
  output_file?: string;
}

export const fetchSessions = async (): Promise<SessionSummary[]> => {
  try {
    const res = await fetch(`${CONFIG_AGENT_URL}/sessions`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
};

export const fetchSession = async (sessionId: string): Promise<SessionDetail | null> => {
  try {
    const res = await fetch(`${CONFIG_AGENT_URL}/sessions/${sessionId}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
};

export const fetchConfigList = async (): Promise<ConfigListItem[]> => {
  try {
    const res = await fetch(`${CONFIG_AGENT_URL}/configs`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
};

export const fetchConfigFile = async (filename: string): Promise<unknown> => {
  try {
    const res = await fetch(`${CONFIG_AGENT_URL}/output/${filename}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
};

export const chatWithConfigAgent = async (
  message: string,
  sessionId?: string,
  clarificationAnswer?: string,
): Promise<ConfigAgentChatResponse> => {
  const res = await fetch(`${CONFIG_AGENT_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      clarification_answer: clarificationAnswer,
    }),
  });
  if (!res.ok) throw new Error(`Config agent error: ${res.status}`);
  return res.json();
};
