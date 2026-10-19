import terraformMock from './mocks/terraform.json';
import dockerfileMock from './mocks/dockerfile.json';
import yamlMock from './mocks/yaml.json';
import type { AnalysisResult } from './types';

const MOCKS: Record<string, AnalysisResult> = {
  terraform: terraformMock as unknown as AnalysisResult,
  dockerfile: dockerfileMock as unknown as AnalysisResult,
  yaml: yamlMock as unknown as AnalysisResult,
};

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

export async function analyze(format: string, source: string): Promise<AnalysisResult> {
  if (USE_MOCK) {
    await new Promise(resolve => setTimeout(resolve, 800));
    return MOCKS[format];
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/api/v1/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format, source }),
    });
  } catch {
    throw new Error("Can't reach the server. Check that the backend is running and try again.");
  }

  if (!response.ok) {
    throw new Error(`The server returned an error (${response.status}). Please try again.`);
  }

  return (await response.json()) as AnalysisResult;
}