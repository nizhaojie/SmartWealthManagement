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
