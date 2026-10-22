// Response contract of POST /api/v1/validate (docs/api.md, PROJECT_SPEC 3 and 7.3).
// Mirrors the backend Pydantic models in backend/app/models/.

// 'mixed' is multi-file only: each file's format is detected from its name.
export type SourceFormat = 'yaml' | 'dockerfile' | 'terraform' | 'mixed';
export type Severity = 'error' | 'warning' | 'info';
export type FixKind = 'deterministic' | 'judgment';
export type Metadata = Record<string, unknown>;

// All positions are 1-based and any of them may be null.
// end_column is EXCLUSIVE: it points one past the last character.
export interface SourceLocation {
  file: string | null;
  start_line: number | null;
  start_column: number | null;
  end_line: number | null;
  end_column: number | null;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  source_location: SourceLocation | null;
  metadata: Metadata;
}

// source -> target means "source must come before target" (target depends on source).
export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  label: string | null;
  source_location: SourceLocation | null;
  metadata: Metadata;
}

export interface Diagnostic {
  code: string;
  severity: Severity;
  message: string;
  source_location: SourceLocation | null;
}

export interface ProposedChange {
  description: string;
  preview: string | null;
  source_location: SourceLocation | null;
  /** Unified diff the user can apply with `git apply`; the tool never applies it. */
  patch?: string | null;
}

export interface Recommendation {
  id: string;
  rule_id: string;
  title: string;
  explanation: string;
  diagnostic_code: string;
  diagnostic_index: number; // index into AnalysisResult.diagnostics
  fix_kind: FixKind;
  proposed_change: ProposedChange | null;
  source_location: SourceLocation | null;
  related_node_ids: string[];
}

export interface InterFileDependency {
  source_node: string;
  target_node: string;
  source_file: string;
  target_file: string;
  edge_type: string;
  symbol: string | null;
}

export interface VariableOccurrence {
  name: string;
  declared_files: string[];
  referenced_files: string[];
  total_occurrences: number;
  is_duplicate: boolean;
  is_unused: boolean;
  locations: SourceLocation[];
}

export interface MultiFileSummary {
  files: string[];
  /** format "mixed" only: what each file was analysed as. */
  file_formats?: Record<string, string>;
  interfile_dependencies: InterFileDependency[];
  variable_occurrences: VariableOccurrence[];
  duplicate_variables: string[];
  unused_variables: string[];
}

export interface AnalysisResult {
  valid: boolean;
  format: SourceFormat;
  diagnostics: Diagnostic[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
  execution_order: string[] | null;
  recommendations: Recommendation[];
  multifile?: MultiFileSummary | null;
}

export interface FileItem {
  id: string;
  name: string;
  content: string;
}
