export interface SourceLocation {
  file: string;
  start_line: number;
  start_column: number;
  end_line: number;
  end_column: number;
}

export interface Diagnostic {
  code: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  source_location: SourceLocation;
}

export interface Recommendation {
  id: string;
  title: string;
  explanation: string;
  proposed_change: { description: string; preview: string } | null;
  related_node_ids: string[];
}

export interface AnalysisResult {
  valid: boolean;
  format: string;
  diagnostics: Diagnostic[];
  recommendations: Recommendation[];
  execution_order: string[] | null;
}