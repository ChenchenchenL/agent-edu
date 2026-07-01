export interface QuizQuestion {
  prompt: string;
  answer: string;
}

export interface QuizDraft {
  quiz_id: string;
  session_id: string;
  topic: string;
  difficulty: string;
  question_count: number;
  questions: QuizQuestion[];
  skill_trace: string[];
  created_at: string;
}

export interface QuizSummary {
  quiz_id: string;
  session_id: string;
  topic: string;
  difficulty: string;
  question_count: number;
  skill_trace: string[];
  created_at: string;
}

export interface GenerateQuizRequest {
  topic: string;
  difficulty: string;
  question_count: number;
}
