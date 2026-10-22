import { useRef, useState, type ChangeEvent } from 'react';
import type { AnalysisResult, Diagnostic, FileItem, SourceFormat, SourceLocation } from './types';
import { analyze, analyzeMultiFile } from './api';
import {
  diagnosticNodeIds,
  formatLocation,
  getStatus,
  isPartial,
  selectionRange,
  type StatusTone,
} from './analysis';
import DependencyGraph from './components/DependencyGraph';
import NodeDetails from './components/NodeDetails';
import MultiFilePanel from './components/MultiFilePanel';
import terraformSample from './samples/main.tf?raw';
import dockerfileSample from './samples/Dockerfile?raw';
import yamlSample from './samples/ci.yml?raw';

// The same files are used to generate the mocks (frontend/scripts/generate_mocks.py).
const SAMPLES: Record<SourceFormat, string> = {
  terraform: terraformSample,
  dockerfile: dockerfileSample,
  yaml: yamlSample,
};

const MULTIFILE_TERRAFORM_SAMPLE: { name: string; content: string }[] = [
  {
    name: 'variables.tf',
    content: `variable "environment" {
  type    = string
  default = "production"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "unused_token" {
  type    = string
  default = "deprecated"
}
`,
  },
  {
    name: 'main.tf',
    content: `resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr

  tags = {
    Environment = var.environment
  }
}

resource "aws_subnet" "public" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.0.1.0/24"

  tags = {
    Environment = var.environment
  }
}

resource "aws_instance" "web" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = var.instance_type
  subnet_id     = aws_subnet.public.id

  tags = {
    Environment = var.environment
  }
}
`,
  },
  {
    name: 'outputs.tf',
    content: `output "vpc_id" {
  value = aws_vpc.main.id
}

output "web_instance_id" {
  value = aws_instance.web.id
}
`,
  },
];

const STATUS_STYLES: Record<StatusTone, string> = {
  valid: 'bg-green-100 text-green-700',
  warning: 'bg-amber-100 text-amber-700',
  error: 'bg-red-100 text-red-700',
};

const FEATURES = [
  { icon: '🕸️', title: 'Dependency graph', text: 'See how every resource, stage or task connects.' },
  { icon: '🔍', title: 'Inter-file & variable checks', text: 'Detect cross-file dependencies and duplicate variable definitions.' },
  { icon: '🛠️', title: 'Suggested fixes', text: 'Get clear recommendations with a preview of the change.' },
];

const SEVERITY_STYLES: Record<string, { card: string; title: string }> = {
  error: {
    card: 'border-red-200 bg-red-50 hover:bg-red-100',
    title: 'text-red-700',
  },
  warning: {
    card: 'border-amber-200 bg-amber-50 hover:bg-amber-100',
    title: 'text-amber-700',
  },
  info: {
    card: 'border-sky-200 bg-sky-50 hover:bg-sky-100',
    title: 'text-sky-700',
  },
};

function detectLanguage(fileName: string): SourceFormat | null {
  const name = fileName.toLowerCase();
  if (name.endsWith('.tf')) return 'terraform';
  if (/^(dockerfile|containerfile)|\.(dockerfile|containerfile)$/.test(name)) return 'dockerfile';
  if (name.endsWith('.yml') || name.endsWith('.yaml')) return 'yaml';
  return null;
}

export default function App() {
  const [language, setLanguage] = useState<SourceFormat>('terraform');
  const [files, setFiles] = useState<FileItem[]>([{ id: '1', name: '', content: '' }]);
  const [activeFileId, setActiveFileId] = useState<string>('1');
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [uploadNote, setUploadNote] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState<ReadonlySet<string>>(new Set());
  const [activeDiagnostic, setActiveDiagnostic] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const activeFile = files.find(f => f.id === activeFileId) ?? files[0];
  const code = activeFile?.content ?? '';
  const isMultiFile = files.length > 1;

  function updateActiveFileContent(newContent: string) {
    setFiles(prev =>
      prev.map(f => (f.id === activeFileId ? { ...f, content: newContent } : f))
    );
  }

  async function handleAnalyze() {
    const hasAnyContent = files.some(f => f.content.trim() !== '');
    if (!hasAnyContent) {
      setResult(null);
      setError('Please paste some code, load a sample or upload a file first.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);
    selectNode(null);

    try {
      if (files.length > 1) {
        // Multi-file validation
        const payload = files.map((f, i) => ({
          filename: f.name || `file_${i + 1}.${language === 'terraform' ? 'tf' : language === 'yaml' ? 'yml' : 'dockerfile'}`,
          content: f.content,
        }));
        const data = await analyzeMultiFile(language, payload);
        setResult(data);
      } else {
        // Single file validation (backwards compatible with tests)
        const single = files[0];
        const data = await analyze(language, single.content, single.name || undefined);
        setResult(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  async function handleFiles(e: ChangeEvent<HTMLInputElement>) {
    const uploaded = e.target.files;
    if (!uploaded || uploaded.length === 0) return;

    const newFiles: FileItem[] = [];
    for (let i = 0; i < uploaded.length; i++) {
      const file = uploaded[i];
      const text = await file.text();
      newFiles.push({
        id: String(Date.now() + i),
        name: file.name,
        content: text,
      });
    }

    setFiles(newFiles);
    setActiveFileId(newFiles[0].id);
    setResult(null);
    setError('');

    // Scripts and other build-context files (build.sh, package.json) don't
    // name a format, so use the first file that does.
    const firstDetected = newFiles.map(f => detectLanguage(f.name)).find(Boolean) ?? null;
    if (firstDetected) {
      setLanguage(firstDetected);
      const others = newFiles.filter(f => detectLanguage(f.name) === null).length;
      setUploadNote(
        newFiles.length > 1
          ? `Loaded ${newFiles.length} files (${firstDetected}).` +
              (firstDetected === 'dockerfile' && others > 0
                ? ` ${others} other file(s) are treated as build context: COPY sources and scripts run by RUN are checked.`
                : '')
          : ''
      );
    } else {
      setUploadNote("Couldn't determine format from file extension. Please select above.");
    }

    e.target.value = '';
  }

  function handleAddFile() {
    const ext = language === 'terraform' ? '.tf' : language === 'yaml' ? '.yml' : '.dockerfile';
    const nextNum = files.length + 1;
    const newFile: FileItem = {
      id: String(Date.now()),
      name: `module_${nextNum}${ext}`,
      content: '',
    };
    setFiles(prev => [...prev, newFile]);
    setActiveFileId(newFile.id);
  }

  function handleRemoveFile(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (files.length <= 1) return;
    const remaining = files.filter(f => f.id !== id);
    setFiles(remaining);
    if (activeFileId === id) {
      setActiveFileId(remaining[0].id);
    }
  }

  function loadSingleSample() {
    setFiles([{ id: '1', name: '', content: SAMPLES[language] }]);
    setActiveFileId('1');
    setUploadNote('');
    setError('');
    setResult(null);
  }

  function loadMultiFileSample() {
    setLanguage('terraform');
    const newFiles = MULTIFILE_TERRAFORM_SAMPLE.map((s, i) => ({
      id: String(Date.now() + i),
      name: s.name,
      content: s.content,
    }));
    setFiles(newFiles);
    setActiveFileId(newFiles[1].id); // focus main.tf by default
    setUploadNote('Loaded 3-file Terraform module sample (variables.tf, main.tf, outputs.tf)');
    setError('');
    setResult(null);
  }

  function selectNode(id: string | null) {
    setSelectedNodeId(id);
    setHighlighted(new Set(id ? [id] : []));
    setActiveDiagnostic(null);
  }

  // A diagnostic highlights its nodes (spec 8.2 step 6), opens the first one's
  // details and moves the editor to its location.
  function selectDiagnostic(index: number) {
    if (!result) return;
    const ids = diagnosticNodeIds(result, index);
    setActiveDiagnostic(index);
    setHighlighted(new Set(ids));
    setSelectedNodeId(ids[0] ?? null);
    const loc = result.diagnostics[index]?.source_location ?? null;
    jumpTo(loc);
  }

  function jumpTo(location: Diagnostic['source_location']) {
    if (location?.file) {
      const target = files.find(f => f.name === location.file);
      if (target && target.id !== activeFileId) {
        setActiveFileId(target.id);
      }
    }
    setTimeout(() => {
      const el = textareaRef.current;
      const targetCode = files.find(f => (location?.file ? f.name === location.file : f.id === activeFileId))?.content ?? code;
      const range = selectionRange(targetCode, location);
      if (!el || !range || location?.start_line == null) return;
      el.focus();
      el.setSelectionRange(range.start, range.end);
      el.scrollTop = Math.max(0, (location.start_line - 3) * 20);
    }, 50);
  }

  function jumpToFile(filename: string, location?: SourceLocation | null) {
    const target = files.find(f => f.name === filename);
    if (target) {
      setActiveFileId(target.id);
    }
    if (location) {
      jumpTo(location);
    }
  }

  const status = result ? getStatus(result) : null;
  const selectedNode = result?.graph.nodes.find(n => n.id === selectedNodeId) ?? null;
  const partial = result ? isPartial(result) : false;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-gradient-to-r from-slate-900 via-indigo-900 to-slate-900 px-8 py-12 text-center text-white">
        <h1 className="text-4xl font-bold">Cloud Workflow Validator</h1>
        <p className="mx-auto mt-3 max-w-xl text-lg text-indigo-100">
          Analyze configuration dependencies, cross-file variables, and issues before deployment.
        </p>
      </header>

      <main className="mx-auto max-w-6xl p-8">
        <div className="mb-8 grid gap-4 sm:grid-cols-3">
          {FEATURES.map(f => (
            <div key={f.title} className="rounded-xl bg-white p-5 shadow-xs">
              <div className="text-2xl">{f.icon}</div>
              <h3 className="mt-2 font-semibold text-slate-900">{f.title}</h3>
              <p className="mt-1 text-sm text-slate-600">{f.text}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Editor & Configuration Section */}
          <section className="rounded-xl bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <label className="text-sm font-medium text-slate-700">
                Input format
                <select
                  value={language}
                  onChange={e => setLanguage(e.target.value as SourceFormat)}
                  className="mt-1 block w-44 rounded-md border border-slate-300 p-2 text-sm"
                >
                  <option value="terraform">Terraform</option>
                  <option value="dockerfile">Dockerfile</option>
                  <option value="yaml">YAML</option>
                </select>
              </label>

              <div className="flex flex-wrap items-center gap-3 text-sm font-medium">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="text-indigo-600 hover:underline"
                >
                  Upload file(s)
                </button>
                <button
                  type="button"
                  onClick={loadSingleSample}
                  className="text-indigo-600 hover:underline"
                >
                  Load sample
                </button>
                {language === 'terraform' && (
                  <button
                    type="button"
                    onClick={loadMultiFileSample}
                    className="rounded bg-indigo-50 px-2 py-1 text-xs text-indigo-700 hover:bg-indigo-100"
                    title="Load multi-file Terraform module with main.tf, variables.tf, and outputs.tf"
                  >
                    Load multi-file sample
                  </button>
                )}
              </div>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".tf,.yml,.yaml,.dockerfile,Dockerfile,*"
              onChange={handleFiles}
              className="hidden"
            />

            {/* Multi-file tabs bar */}
            <div className="mt-4 flex items-center justify-between border-b border-slate-200 pb-2">
              <div className="flex flex-wrap items-center gap-1.5 overflow-x-auto">
                {files.map((file, idx) => {
                  const isActive = file.id === activeFileId;
                  const label = file.name || (files.length === 1 ? 'untitled' : `file_${idx + 1}`);
                  const hasErr = result?.diagnostics.some(
                    d => d.source_location?.file === file.name && d.severity === 'error'
                  );
                  return (
                    <div
                      key={file.id}
                      onClick={() => setActiveFileId(file.id)}
                      className={`group flex cursor-pointer items-center gap-1.5 rounded-t-md px-3 py-1.5 text-xs font-mono transition-colors ${
                        isActive
                          ? 'border-b-2 border-indigo-600 bg-indigo-50 font-semibold text-indigo-900'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900'
                      }`}
                    >
                      {hasErr && <span className="h-1.5 w-1.5 rounded-full bg-red-500" title="Has errors" />}
                      <span className="truncate max-w-[120px]">{label}</span>
                      {files.length > 1 && (
                        <button
                          type="button"
                          onClick={e => handleRemoveFile(file.id, e)}
                          className="ml-1 text-slate-400 hover:text-red-600"
                          title="Remove file"
                        >
                          ×
                        </button>
                      )}
                    </div>
                  );
                })}
                <button
                  type="button"
                  onClick={handleAddFile}
                  className="rounded px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-50"
                  title="Add another file"
                >
                  + Add file
                </button>
              </div>

              {isMultiFile && (
                <span className="ml-2 shrink-0 rounded bg-indigo-100 px-2 py-0.5 text-[11px] font-semibold text-indigo-800">
                  {files.length} files
                </span>
              )}
            </div>

            {uploadNote && <p className="mt-2 text-xs text-amber-600">{uploadNote}</p>}

            <textarea
              ref={textareaRef}
              value={code}
              onChange={e => updateActiveFileContent(e.target.value)}
              placeholder={`Paste your ${activeFile.name ? activeFile.name : language} code here, or upload multiple files`}
              rows={14}
              spellCheck={false}
              className="mt-2 w-full rounded-md border border-slate-300 p-3 font-mono text-sm leading-5 focus:border-indigo-500 focus:outline-hidden"
            />

            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={handleAnalyze}
                disabled={loading}
                className="rounded-md bg-indigo-600 px-5 py-2 font-semibold text-white shadow-xs hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Analyzing...' : isMultiFile ? `Analyze ${files.length} files` : 'Analyze'}
              </button>

              {isMultiFile && (
                <span className="text-xs text-slate-500">
                  Cross-file variable references and dependencies will be checked.
                </span>
              )}
            </div>
          </section>

          {/* Results Section */}
          {loading ? (
            <section className="flex min-h-80 flex-col items-center justify-center rounded-xl bg-white p-6 text-center shadow-sm">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-indigo-600" />
              <h2 className="mt-4 text-lg font-semibold text-slate-800">Analyzing your configuration...</h2>
              <p className="mt-1 text-sm text-slate-500">
                Resolving cross-file dependencies and tracking variable occurrences.
              </p>
            </section>
          ) : error ? (
            <section className="flex min-h-80 flex-col items-center justify-center rounded-xl border border-red-200 bg-red-50 p-6 text-center">
              <div className="text-4xl">⚠️</div>
              <h2 className="mt-3 text-lg font-semibold text-red-700">Couldn't analyze</h2>
              <p className="mt-1 max-w-sm text-sm text-red-600">{error}</p>
            </section>
          ) : result === null || status === null ? (
            <section className="flex min-h-80 flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 bg-white/60 p-6 text-center">
              <div className="text-5xl">🕸️</div>
              <h2 className="mt-3 text-lg font-semibold text-slate-800">
                Your dependency graph will appear here
              </h2>
              <p className="mt-1 max-w-xs text-sm text-slate-500">
                Choose a format, load a sample or upload multiple files, then click Analyze.
              </p>
            </section>
          ) : (
            <section className="rounded-xl bg-white p-6 shadow-sm">
              <div className="flex items-center justify-between">
                <span className={`rounded-full px-3 py-1 text-sm font-semibold ${STATUS_STYLES[status.tone]}`}>
                  {status.label}
                </span>
                {result.multifile && result.multifile.files.length > 1 && (
                  <span className="rounded bg-indigo-50 px-2 py-1 font-mono text-xs text-indigo-700">
                    Validated {result.multifile.files.length} files
                  </span>
                )}
              </div>

              {partial && (
                <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
                  <span className="font-semibold">Partial analysis.</span> Some constructs could not be
                  analysed, so the graph may be missing dependencies. See the unsupported-construct
                  warnings below.
                </div>
              )}

              <DependencyGraph
                result={result}
                highlighted={highlighted}
                onSelectNode={selectNode}
              />

              {selectedNode && (
                <NodeDetails
                  result={result}
                  node={selectedNode}
                  onJump={jumpTo}
                  onSelectDiagnostic={selectDiagnostic}
                  onClose={() => selectNode(null)}
                />
              )}

              {/* Multi-File Cross-Boundary & Variable Analysis */}
              {result.multifile && result.multifile.files.length > 1 && (
                <MultiFilePanel
                  summary={result.multifile}
                  onJumpToFile={jumpToFile}
                />
              )}

              <h2 className="mt-6 font-semibold text-slate-900">Diagnostics</h2>
              {result.diagnostics.length === 0 && (
                <p className="mt-2 text-sm text-slate-500">No issues found.</p>
              )}
              <ul className="mt-2 space-y-2">
                {result.diagnostics.map((d, i) => {
                  const s = SEVERITY_STYLES[d.severity] ?? SEVERITY_STYLES.info;
                  const where = formatLocation(d.source_location);
                  const linked = diagnosticNodeIds(result, i).length > 0;
                  const clickable = where !== null || linked;
                  return (
                    <li
                      key={i}
                      onClick={clickable ? () => selectDiagnostic(i) : undefined}
                      className={`rounded-md border p-3 text-sm ${s.card} ${clickable ? 'cursor-pointer' : ''} ${activeDiagnostic === i ? 'ring-2 ring-indigo-400' : ''}`}
                    >
                      <div className={`font-semibold ${s.title}`}>
                        {d.severity.toUpperCase()} · {d.code}
                        {where && ` · ${where}`}
                      </div>
                      <div className="mt-1 text-slate-700">{d.message}</div>
                      {clickable && (
                        <div className="mt-1 text-xs text-slate-500">
                          {where && linked
                            ? 'Click to show it in the editor and the graph'
                            : where
                              ? 'Click to jump to this location'
                              : 'Click to show it in the graph'}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>

              {result.recommendations.length > 0 && (
                <h2 className="mt-5 font-semibold text-slate-900">Suggested fixes</h2>
              )}
              {result.recommendations.map(r => (
                <div key={r.id} className="mt-2 rounded-md border border-indigo-200 bg-indigo-50 p-3 text-sm">
                  <div className="font-semibold text-indigo-800">{r.title}</div>
                  <div className="mt-1 text-slate-700">{r.explanation}</div>
                  {r.proposed_change && (
                    <div className="mt-2">
                      <div className="text-slate-700">
                        <span className="font-medium">Suggested change:</span>{' '}
                        {r.proposed_change.description}
                      </div>
                      {r.proposed_change.preview !== null && (
                        <pre className="mt-2 rounded bg-slate-900 p-2 text-xs text-green-300">
                          {r.proposed_change.preview}
                        </pre>
                      )}
                    </div>
                  )}
                  {r.fix_kind === 'judgment' && (
                    <div className="mt-2 text-xs text-slate-500">
                      Review before applying: this tool never changes your files.
                    </div>
                  )}
                </div>
              ))}
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
