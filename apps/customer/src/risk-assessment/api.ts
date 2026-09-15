import { http } from "../api/http";
import type { AssessmentResult, Questionnaire } from "./types";

export function getQuestionnaire(): Promise<Questionnaire> {
  return http.get<Questionnaire>("/api/customer/risk-assessment/questionnaire");
}

export function saveDraft(answers: Record<string, string>): Promise<{ answers: Record<string, string> }> {
  return http.put<{ answers: Record<string, string> }>("/api/customer/risk-assessment/draft", { answers });
}

export function submitAssessment(answers: Record<string, string>): Promise<AssessmentResult> {
  return http.post<AssessmentResult>("/api/customer/risk-assessment", { answers });
}

export function getCurrentAssessment(): Promise<AssessmentResult> {
  return http.get<AssessmentResult>("/api/customer/risk-assessment");
}
