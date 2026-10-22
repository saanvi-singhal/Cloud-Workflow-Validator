import { useMemo, useRef, useState, type ChangeEvent } from 'react';
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
import CompareView from './components/CompareView';
import PatchBlock from './components/PatchBlock';
import AdvisorPanel from './components/AdvisorPanel';
import { blastRadius } from './blastRadius';
import terraformSample from './samples/main.tf?raw';
import dockerfileSample from './samples/Dockerfile?raw';
import yamlSample from './samples/ci.yml?raw';
import mixedWorkflow from './samples/mixed/ci.yml?raw';
import mixedDockerfile from './samples/mixed/Dockerfile?raw';
import mixedInstallScript from './samples/mixed/install-tools.sh?raw';
import mixedScanScript from './samples/mixed/scan.sh?raw';

// The same files are used to generate the mocks (frontend/scripts/generate_mocks.py).
const SAMPLES: Record<Exclude<SourceFormat, 'mixed'>, string> = {
  terraform: terraformSample,
  dockerfile: dockerfileSample,
  yaml: yamlSample,
};

// A workflow, a Dockerfile and the scripts it uses, analysed together.
const MIXED_SAMPLE: { name: string; content: string }[] = [
  { name: 'ci.yml', content: mixedWorkflow },
  { name: 'Dockerfile', content: mixedDockerfile },
  { name: 'install-tools.sh', content: mixedInstallScript },
  { name: 'scan.sh', content: mixedScanScript },
];

const FILE_EXTENSION: Record<SourceFormat, string> = {
  terraform: '.tf',
  yaml: '.yml',
  dockerfile: '.dockerfile',
  mixed: '.txt',
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
  valid: 'bg-emerald-100 text-emerald-800 border border-emerald-200',
  warning: 'bg-amber-100 text-amber-800 border border-amber-200',
  error: 'bg-red-100 text-red-800 border border-red-200',
};

const FEATURES = [
  {
    icon: (
      <svg className="h-5 w-5 text-sky-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" strokeDasharray="3 3" />
        <circle cx="12" cy="12" r="3" />
        <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
      </svg>
    ),
    title: 'Dependency graph',
    text: 'See how every resource, stage or task connects.',
  },
  {
    icon: (
      <svg className="h-5 w-5 text-sky-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M4 6h16M4 12h16M4 18h16" />
        <circle cx="9" cy="6" r="2" fill="currentColor" />
        <circle cx="15" cy="12" r="2" fill="currentColor" />
        <circle cx="9" cy="18" r="2" fill="currentColor" />
      </svg>
    ),
    title: 'Inter-file & variable checks',
    text: 'Detect cross-file dependencies and duplicate variable definitions.',
  },
  {
    icon: (
      <svg className="h-5 w-5 text-sky-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="m9 12 2 2 4-4" />
        <path d="M12 3a9 9 0 1 0 9 9" />
        <path d="M21 3v6h-6" />
      </svg>
    ),
    title: 'Suggested fixes',
    text: 'Get clear recommendations with a preview of the change.',
  },
];

const SEVERITY_STYLES: Record<string, { card: string; title: string }> = {
  error: {
    card: 'border-red-200 bg-red-50/70 hover:bg-red-100/70',
    title: 'text-red-700',
  },
  warning: {
    card: 'border-amber-200 bg-amber-50/70 hover:bg-amber-100/70',
    title: 'text-amber-700',
  },
  info: {
    card: 'border-sky-200 bg-sky-50/70 hover:bg-sky-100/70',
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

/** 'mixed' when the named files have more than one format, else that format. */
function detectFormats(names: string[]): SourceFormat | null {
  const found = new Set(names.map(detectLanguage).filter(f => f !== null));
  if (found.size > 1) return 'mixed';
  return found.size === 1 ? [...found][0] : null;
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
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [showBlast, setShowBlast] = useState(false);
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

  function handleClearCurrentInput() {
    updateActiveFileContent('');
    setError('');
    textareaRef.current?.focus();
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
      // Mixed mode always sends files: the backend detects each one's format.
      if (files.length > 1 || language === 'mixed') {
        // Multi-file validation
        const payload = files.map((f, i) => ({
          filename: f.name || `file_${i + 1}${FILE_EXTENSION[language]}`,
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
    // name a format; several formats together are analysed as 'mixed'.
    const firstDetected = detectFormats(newFiles.map(f => f.name));
    if (firstDetected) {
      setLanguage(firstDetected);
      const others = newFiles.filter(f => detectLanguage(f.name) === null).length;
      const hasDockerfile = newFiles.some(f => detectLanguage(f.name) === 'dockerfile');
      setUploadNote(
        newFiles.length > 1
          ? (firstDetected === 'mixed'
              ? `Loaded ${newFiles.length} files of different formats: each is analysed with its own parser.`
              : `Loaded ${newFiles.length} files (${firstDetected}).`) +
              (hasDockerfile && others > 0
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
    const nextNum = files.length + 1;
    const newFile: FileItem = {
      id: String(Date.now()),
      name: `module_${nextNum}${FILE_EXTENSION[language]}`,
      content: '',
    };
    setFiles(prev => [...prev, newFile]);
    setActiveFileId(newFile.id);
    // Name it straight away, e.g. build.sh next to a Dockerfile.
    setRenamingId(newFile.id);
  }

  function renameFile(id: string, rawName: string) {
    setRenamingId(null);
    const name = rawName.trim();
    const current = files.find(f => f.id === id);
    if (!current || !name || name === current.name) return;
    if (files.some(f => f.id !== id && f.name === name)) {
      setUploadNote(`There is already a file named ${name}.`);
      return;
    }
    const renamed = files.map(f => (f.id === id ? { ...f, name } : f));
    setFiles(renamed);
    setUploadNote('');
    // Adding e.g. ci.yml next to a Dockerfile switches to mixed analysis.
    const detected = detectFormats(renamed.map(f => f.name));
    if (detected === 'mixed') setLanguage('mixed');
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
    if (language === 'mixed') {
      loadMixedSample();
      return;
    }
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

  function loadMixedSample() {
    const newFiles = MIXED_SAMPLE.map((s, i) => ({
      id: String(Date.now() + i),
      name: s.name,
      content: s.content,
    }));
    setFiles(newFiles);
    setActiveFileId(newFiles[1].id); // the Dockerfile
    setUploadNote(
      'Loaded a workflow, a Dockerfile and the two scripts it copies; each is analysed with its own parser.',
    );
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
  // Everything downstream of the selected node ("click a node, see what breaks").
  const blast = useMemo(
    () => (result && selectedNodeId ? blastRadius(result, selectedNodeId) : undefined),
    [result, selectedNodeId],
  );
  const partial = result ? isPartial(result) : false;

  return (
    <div className="min-h-screen bg-slate-50/70 text-slate-800">
      {/* Light Clean Aero Header */}
      <header className="border-b border-slate-200/80 bg-gradient-to-b from-sky-50/60 via-white to-white px-8 py-10 text-center">
        <div className="inline-flex items-center gap-1.5 rounded-full border border-sky-200/80 bg-sky-50/80 px-3 py-1 text-xs font-medium text-sky-800 mb-3 shadow-2xs">
          <svg className="h-3.5 w-3.5 text-sky-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
          </svg>
          Pre-deployment validator
        </div>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900">
          Cloud Workflow Validator
        </h1>
        <p className="mx-auto mt-2.5 max-w-xl text-base text-slate-600">
          Analyze configuration dependencies, cross-file variables, and issues before deployment.
        </p>
      </header>

      <main className="mx-auto max-w-6xl p-6 sm:p-8">
        {/* Description Cards - Clean Aero Style */}
        <div className="mb-8 grid gap-4 sm:grid-cols-3">
          {FEATURES.map(f => (
            <div
              key={f.title}
              className="flex items-start gap-3.5 rounded-xl border border-slate-200/80 bg-white p-5 shadow-xs transition-all hover:border-sky-300 hover:shadow-sm"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600 border border-sky-100 shadow-2xs">
                {f.icon}
              </div>
              <div className="min-w-0">
                <h3 className="font-semibold text-slate-900 text-sm tracking-tight">{f.title}</h3>
                <p className="mt-1 text-xs text-slate-500 leading-relaxed">{f.text}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="mb-4 flex justify-end">
          <button
            type="button"
            onClick={() => setCompareMode(on => !on)}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-indigo-700 shadow-xs hover:bg-indigo-50"
          >
            {compareMode ? 'Back to analysis' : 'Compare versions'}
          </button>
        </div>

        {compareMode && <CompareView language={language} onLanguageChange={setLanguage} />}

        <div className={compareMode ? 'hidden' : 'grid gap-6 lg:grid-cols-2'}>
          {/* Editor & Configuration Section */}
          <section className="rounded-xl border border-slate-200/90 bg-white p-6 shadow-xs">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <label className="text-sm font-medium text-slate-700">
                Input format
                <select
                  value={language}
                  onChange={e => setLanguage(e.target.value as SourceFormat)}
                  className="mt-1 block w-44 rounded-md border border-slate-300 bg-white p-2 text-sm text-slate-800 focus:border-sky-500 focus:ring-1 focus:ring-sky-500 focus:outline-hidden"
                >
                  <option value="terraform">Terraform</option>
                  <option value="dockerfile">Dockerfile</option>
                  <option value="yaml">YAML</option>
                  <option value="mixed">Mixed (detect each file)</option>
                </select>
              </label>

              <div className="flex flex-wrap items-center gap-2.5 text-sm font-medium">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="text-sky-600 hover:text-sky-700 hover:underline"
                >
                  Upload file(s)
                </button>
                <button
                  type="button"
                  onClick={loadSingleSample}
                  className="text-sky-600 hover:text-sky-700 hover:underline"
                >
                  Load sample
                </button>
                {language === 'terraform' && (
                  <button
                    type="button"
                    onClick={loadMultiFileSample}
                    className="rounded border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs text-sky-700 hover:bg-sky-100 transition-colors"
                    title="Load multi-file Terraform module with main.tf, variables.tf, and outputs.tf"
                  >
                    Load multi-file sample
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleClearCurrentInput}
                  disabled={!code}
                  className="inline-flex items-center gap-1.5 rounded border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600 hover:border-rose-300 hover:bg-rose-50 hover:text-rose-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  title="Clear current input"
                >
                  <svg className="h-3.5 w-3.5 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 6 6 18M6 6l12 12" />
                  </svg>
                  Clear input
                </button>
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
                      className={`group flex cursor-pointer items-center gap-1.5 rounded-t-md px-3 py-1.5 font-mono text-xs transition-colors ${
                        isActive
                          ? 'border-b-2 border-sky-600 bg-sky-50 font-semibold text-sky-900'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900'
                      }`}
                    >
                      {hasErr && <span className="h-1.5 w-1.5 rounded-full bg-red-500" title="Has errors" />}
                      {renamingId === file.id ? (
                        <input
                          autoFocus
                          aria-label="File name"
                          defaultValue={file.name}
                          placeholder="e.g. build.sh"
                          onClick={e => e.stopPropagation()}
                          onBlur={e => renameFile(file.id, e.target.value)}
                          onKeyDown={e => {
                            if (e.key === 'Enter') renameFile(file.id, e.currentTarget.value);
                            if (e.key === 'Escape') setRenamingId(null);
                          }}
                          className="w-28 rounded border border-sky-400 bg-white px-1 font-mono text-xs text-slate-900 focus:outline-hidden"
                        />
                      ) : (
                        <span
                          className="truncate max-w-[120px]"
                          title="Double-click to rename"
                          onDoubleClick={() => setRenamingId(file.id)}
                        >
                          {label}
                        </span>
                      )}
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
                  className="rounded px-2 py-1 font-mono text-xs text-sky-600 hover:bg-sky-50 transition-colors"
                  title="Add another file"
                >
                  + Add file
                </button>
              </div>

              {isMultiFile && (
                <span className="ml-2 shrink-0 rounded bg-sky-100 px-2 py-0.5 text-[11px] font-semibold text-sky-800">
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
              className="mt-3 w-full rounded-lg border border-slate-300 bg-slate-50/50 p-3.5 font-mono text-xs leading-relaxed text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:bg-white focus:ring-1 focus:ring-sky-500 focus:outline-hidden"
            />

            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={handleAnalyze}
                disabled={loading}
                className="rounded-lg bg-sky-600 px-6 py-2.5 font-semibold text-xs text-white shadow-xs hover:bg-sky-500 active:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
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
            <section className="flex min-h-80 flex-col items-center justify-center rounded-xl border border-slate-200/90 bg-white p-6 text-center shadow-xs">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-sky-600" />
              <h2 className="mt-4 text-base font-semibold text-slate-800">Analyzing your configuration...</h2>
              <p className="mt-1 text-xs text-slate-500">
                Resolving cross-file dependencies and tracking variable occurrences.
              </p>
            </section>
          ) : error ? (
            <section className="flex min-h-80 flex-col items-center justify-center rounded-xl border border-red-200 bg-red-50/80 p-6 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-100 text-red-600 mb-2">
                <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </div>
              <h2 className="mt-2 text-base font-semibold text-red-700">Couldn't analyze</h2>
              <p className="mt-1 max-w-sm text-sm text-red-600">{error}</p>
            </section>
          ) : result === null || status === null ? (
            <section className="flex min-h-80 flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 bg-white/70 p-6 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-sky-50 text-sky-600 border border-sky-100 mb-2 shadow-2xs">
                <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
                  <circle cx="12" cy="12" r="10" strokeDasharray="3 3" />
                  <circle cx="12" cy="12" r="6" />
                  <circle cx="12" cy="12" r="2" fill="currentColor" />
                  <path d="M12 2v20M2 12h20" />
                </svg>
              </div>
              <h2 className="mt-3 text-lg font-semibold text-slate-800">
                Your dependency graph will appear here
              </h2>
              <p className="mt-1 max-w-xs text-sm text-slate-500">
                Choose a format, load a sample or upload multiple files, then click Analyze.
              </p>
            </section>
          ) : (
            <section className="rounded-xl border border-slate-200/90 bg-white p-6 shadow-xs">
              <div className="flex items-center justify-between">
                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${STATUS_STYLES[status.tone]}`}>
                  {status.label}
                </span>
                {result.multifile && result.multifile.files.length > 1 && (
                  <span className="rounded bg-sky-50 border border-sky-200 px-2.5 py-1 font-mono text-xs text-sky-700">
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
                blast={showBlast ? blast : undefined}
              />

              {selectedNode && (
                <NodeDetails
                  result={result}
                  node={selectedNode}
                  onJump={jumpTo}
                  onSelectDiagnostic={selectDiagnostic}
                  onClose={() => selectNode(null)}
                  blast={blast}
                  blastShown={showBlast}
                  onToggleBlast={() => setShowBlast(on => !on)}
                  onSelectNode={selectNode}
                />
              )}

              {/* Multi-File Cross-Boundary & Variable Analysis */}
              {result.multifile && result.multifile.files.length > 1 && (
                <MultiFilePanel
                  summary={result.multifile}
                  onJumpToFile={jumpToFile}
                />
              )}

              <AdvisorPanel result={result} onSelectDiagnostic={selectDiagnostic} />

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
                      className={`rounded-lg border p-3.5 text-sm transition-colors ${s.card} ${clickable ? 'cursor-pointer' : ''} ${activeDiagnostic === i ? 'ring-2 ring-sky-500' : ''}`}
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
                <h2 className="mt-6 font-semibold text-slate-900">Suggested fixes</h2>
              )}
              {result.recommendations.map(r => (
                <div key={r.id} className="mt-2.5 rounded-lg border border-sky-200 bg-sky-50/60 p-4 text-sm">
                  <div className="font-semibold text-sky-900">{r.title}</div>
                  <div className="mt-1 text-slate-700">{r.explanation}</div>
                  {r.proposed_change && (
                    <div className="mt-2">
                      <div className="text-slate-700">
                        <span className="font-medium text-slate-900">Suggested change:</span>{' '}
                        {r.proposed_change.description}
                      </div>
                      {r.proposed_change.patch ? (
                        <PatchBlock patch={r.proposed_change.patch} id={r.id} />
                      ) : (
                        r.proposed_change.preview !== null && (
                          <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-2.5 font-mono text-xs text-green-300">
                            {r.proposed_change.preview}
                          </pre>
                        )
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
