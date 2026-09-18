// 客户侧的风险承受等级只有 C1 到 C5：呈现文案（保守型…激进型）是它在界面上的说法。
export type RiskLevel = "C1" | "C2" | "C3" | "C4" | "C5";

export type QuestionOption = {
  id: string;
  label: string;
};

export type Question = {
  id: string;
  dimension: string;
  prompt: string;
  options: QuestionOption[];
};

export type Questionnaire = {
  questions: Question[];
  answers: Record<string, string>;
};

export type AssessmentResult = {
  risk_level: RiskLevel;
  valid_until: string;
};
