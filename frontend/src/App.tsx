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
  valid: 'border border-emerald-500/50 bg-emerald-950/80 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.25)]',
  warning: 'border border-amber-500/50 bg-amber-950/80 text-amber-300 shadow-[0_0_12px_rgba(245,158,11,0.25)]',
  error: 'border border-rose-500/50 bg-rose-950/80 text-rose-300 shadow-[0_0_12px_rgba(244,63,94,0.3)]',
};

const FEATURES = [
  {
    icon: (
      <svg className="h-6 w-6 text-sky-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
        <circle cx="12" cy="12" r="9" strokeDasharray="3 3" />
        <circle cx="12" cy="12" r="3" />
        <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
        <path d="m5.6 5.6 2.1 2.1M16.3 16.3l2.1 2.1" />
      </svg>
    ),
    tag: 'AVIONICS // 01',
    title: 'Dependency graph',
    text: 'See how every resource, stage or task connects.',
  },
  {
    icon: (
      <svg className="h-6 w-6 text-cyan-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
        <path d="M4 6h16M4 12h16M4 18h16" />
        <circle cx="9" cy="6" r="2" fill="currentColor" />
        <circle cx="15" cy="12" r="2" fill="currentColor" />
        <circle cx="9" cy="18" r="2" fill="currentColor" />
      </svg>
    ),
    tag: 'TELEMETRY // 02',
    title: 'Inter-file & variable checks',
    text: 'Detect cross-file dependencies and duplicate variable definitions.',
  },
  {
    icon: (
      <svg className="h-6 w-6 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
        <path d="m9 12 2 2 4-4" />
        <path d="M12 3a9 9 0 1 0 9 9" />
        <path d="M21 3v6h-6" />
      </svg>
    ),
    tag: 'AUTOPILOT // 03',
    title: 'Suggested fixes',
    text: 'Get clear recommendations with a preview of the change.',
  },
];

const SEVERITY_STYLES: Record<string, { card: string; title: string }> = {
  error: {
    card: 'border-rose-500/40 bg-rose-950/30 hover:bg-rose-950/50 shadow-sm',
    title: 'text-rose-400',
  },
  warning: {
    card: 'border-amber-500/40 bg-amber-950/30 hover:bg-amber-950/50 shadow-sm',
    title: 'text-amber-400',
  },
  info: {
    card: 'border-sky-500/40 bg-sky-950/30 hover:bg-sky-950/50 shadow-sm',
    title: 'text-sky-300',
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
    <div className="min-h-screen bg-[#070b14] text-slate-100 flightdeck-grid relative">
      {/* Cockpit Canopy Top Header */}
      <header className="relative border-b border-sky-500/20 bg-gradient-to-b from-[#0b1329] via-[#080d1a] to-[#070b14] px-8 pt-8 pb-10 text-center shadow-2xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between pb-4">
          <div className="flex items-center gap-2 font-mono text-[11px] tracking-widest text-sky-400">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" />
            AVIONICS ONLINE // SYS-ID: CLOUD-VAL
          </div>
          <div className="hidden sm:flex items-center gap-4 font-mono text-[10px] tracking-wider text-slate-400">
            <span>RADAR: ACTIVE</span>
            <span>•</span>
            <span>DIAGNOSTICS: READY</span>
            <span>•</span>
            <span>CHANNEL: FMC-01</span>
          </div>
        </div>

        <h1 className="text-4xl font-extrabold tracking-tight text-white drop-shadow-md sm:text-5xl">
          Cloud Workflow Validator
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-base text-sky-200/90 font-sans">
          Analyze configuration dependencies, cross-file variables, and issues before deployment.
        </p>

        {/* Flight HUD coordinate strip */}
        <div className="mx-auto mt-4 hidden sm:flex max-w-md items-center justify-center gap-6 rounded-full border border-sky-500/20 bg-slate-950/70 px-4 py-1 font-mono text-[10px] tracking-widest text-sky-400/80 uppercase">
          <span>HDG 042°</span>
          <span>•</span>
          <span>ALT 34,000 FT</span>
          <span>•</span>
          <span>MODE: FLIGHTDECK</span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl p-6 sm:p-8">
        {/* Top Avionics Instrument Cards */}
        <div className="mb-8 grid gap-4 sm:grid-cols-3">
          {FEATURES.map(f => (
            <div
              key={f.title}
              className="aero-glass rounded-xl p-5 shadow-lg transition-all hover:border-sky-500/40"
            >
              <div className="flex items-center justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-sky-500/20 bg-slate-950/80">
                  {f.icon}
                </div>
                <span className="font-mono text-[10px] tracking-wider text-sky-400/70">{f.tag}</span>
              </div>
              <h3 className="mt-3 font-semibold text-white tracking-wide">{f.title}</h3>
              <p className="mt-1 text-sm text-slate-400">{f.text}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Flight Management Computer / Editor Console */}
          <section className="aero-glass-panel rounded-xl p-6 shadow-2xl">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <label className="text-xs font-mono font-semibold uppercase tracking-wider text-sky-300">
                Input format
                <select
                  value={language}
                  onChange={e => setLanguage(e.target.value as SourceFormat)}
                  className="mt-1.5 block w-44 rounded-lg border border-slate-700 bg-slate-950 p-2 font-mono text-xs text-sky-200 focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 focus:outline-hidden"
                >
                  <option value="terraform">Terraform</option>
                  <option value="dockerfile">Dockerfile</option>
                  <option value="yaml">YAML</option>
                </select>
              </label>

              <div className="flex flex-wrap items-center gap-2.5 text-xs font-mono">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="text-cyan-400 hover:text-cyan-300 hover:underline"
                >
                  Upload file(s)
                </button>
                <button
                  type="button"
                  onClick={loadSingleSample}
                  className="text-cyan-400 hover:text-cyan-300 hover:underline"
                >
                  Load sample
                </button>
                {language === 'terraform' && (
                  <button
                    type="button"
                    onClick={loadMultiFileSample}
                    className="rounded border border-sky-500/30 bg-sky-950/60 px-2 py-1 text-sky-300 hover:bg-sky-900/60 transition-colors"
                    title="Load multi-file Terraform module with main.tf, variables.tf, and outputs.tf"
                  >
                    Load multi-file sample
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleClearCurrentInput}
                  disabled={!code}
                  className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-800/80 px-2.5 py-1 text-slate-300 hover:border-rose-500/50 hover:bg-rose-950/30 hover:text-rose-300 disabled:cursor-not-allowed disabled:opacity-40 transition-colors"
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

            {/* Multi-file tabs bar (Cockpit Nav Channels) */}
            <div className="mt-4 flex items-center justify-between border-b border-slate-800 pb-2">
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
                          ? 'border-b-2 border-cyan-400 bg-sky-950/70 font-semibold text-cyan-200 shadow-[0_0_10px_rgba(6,182,212,0.25)]'
                          : 'bg-slate-900/80 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                      }`}
                    >
                      {hasErr && <span className="h-1.5 w-1.5 rounded-full bg-rose-500 shadow-[0_0_6px_#f43f5e]" title="Has errors" />}
                      <span className="truncate max-w-[120px]">{label}</span>
                      {files.length > 1 && (
                        <button
                          type="button"
                          onClick={e => handleRemoveFile(file.id, e)}
                          className="ml-1 text-slate-500 hover:text-rose-400"
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
                  className="rounded border border-dashed border-sky-500/30 px-2 py-1 font-mono text-xs text-sky-400 hover:bg-sky-950/40 hover:text-sky-300 transition-colors"
                  title="Add another file"
                >
                  + Add file
                </button>
              </div>

              {isMultiFile && (
                <span className="ml-2 shrink-0 rounded border border-cyan-500/30 bg-cyan-950/80 px-2 py-0.5 font-mono text-[11px] font-semibold text-cyan-300">
                  {files.length} files
                </span>
              )}
            </div>

            {uploadNote && <p className="mt-2 font-mono text-xs text-amber-400">{uploadNote}</p>}

            {/* CRT Cockpit Editor Terminal */}
            <textarea
              ref={textareaRef}
              value={code}
              onChange={e => updateActiveFileContent(e.target.value)}
              placeholder={`Paste your ${activeFile.name ? activeFile.name : language} code here, or upload multiple files`}
              rows={14}
              spellCheck={false}
              className="mt-3 w-full rounded-lg border border-slate-800 bg-slate-950/90 p-3.5 font-mono text-xs leading-relaxed text-sky-100 placeholder:text-slate-600 focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/50 focus:outline-hidden"
            />

            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={handleAnalyze}
                disabled={loading}
                className="rounded-lg bg-gradient-to-r from-sky-500 to-cyan-400 px-6 py-2.5 font-mono text-xs font-bold uppercase tracking-wider text-slate-950 shadow-[0_0_20px_rgba(56,189,248,0.35)] hover:from-sky-400 hover:to-cyan-300 active:from-sky-600 active:to-cyan-500 disabled:cursor-not-allowed disabled:opacity-50 transition-all"
              >
                {loading ? 'Analyzing...' : isMultiFile ? `Analyze ${files.length} files` : 'Analyze'}
              </button>

              {isMultiFile && (
                <span className="font-mono text-xs text-slate-400">
                  Cross-file variable references and dependencies will be checked.
                </span>
              )}
            </div>
          </section>

          {/* Results / Multi-Function Display (MFD) Section */}
          {loading ? (
            <section className="aero-glass-panel flex min-h-80 flex-col items-center justify-center rounded-xl p-6 text-center shadow-2xl">
              <div className="relative flex h-14 w-14 items-center justify-center">
                <div className="absolute inset-0 animate-ping rounded-full border border-sky-400/40" />
                <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-800 border-t-cyan-400" />
              </div>
              <h2 className="mt-5 font-mono text-base font-semibold uppercase tracking-wider text-white">
                Analyzing your configuration...
              </h2>
              <p className="mt-1 font-mono text-xs text-slate-400">
                Resolving cross-file dependencies and tracking variable occurrences.
              </p>
            </section>
          ) : error ? (
            <section className="flex min-h-80 flex-col items-center justify-center rounded-xl border border-rose-500/40 bg-rose-950/30 p-6 text-center shadow-xl">
              <div className="flex h-12 w-12 items-center justify-center rounded-full border border-rose-500/40 bg-rose-950/60 shadow-[0_0_15px_rgba(244,63,94,0.3)]">
                <svg className="h-6 w-6 text-rose-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </div>
              <h2 className="mt-3 font-mono text-base font-semibold text-rose-400">Couldn't analyze</h2>
              <p className="mt-1 max-w-sm text-sm text-rose-200/90">{error}</p>
            </section>
          ) : result === null || status === null ? (
            <section className="aero-glass-panel flex min-h-80 flex-col items-center justify-center rounded-xl border-2 border-dashed border-sky-500/20 p-6 text-center shadow-2xl">
              <div className="flex h-14 w-14 items-center justify-center rounded-full border border-sky-500/30 bg-sky-950/50 shadow-[0_0_20px_rgba(56,189,248,0.2)]">
                <svg className="h-8 w-8 text-sky-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
                  <circle cx="12" cy="12" r="10" strokeDasharray="3 3" />
                  <circle cx="12" cy="12" r="6" />
                  <circle cx="12" cy="12" r="2" fill="currentColor" />
                  <path d="M12 2v20M2 12h20" />
                  <path d="m12 12 7-7" strokeWidth="2" />
                </svg>
              </div>
              <h2 className="mt-4 text-lg font-semibold text-white">
                Your dependency graph will appear here
              </h2>
              <p className="mt-1 max-w-xs text-sm text-slate-400">
                Choose a format, load a sample or upload multiple files, then click Analyze.
              </p>
            </section>
          ) : (
            <section className="aero-glass-panel rounded-xl p-6 shadow-2xl">
              <div className="flex items-center justify-between">
                <span className={`rounded-full px-3 py-1 font-mono text-xs font-semibold uppercase tracking-wider ${STATUS_STYLES[status.tone]}`}>
                  {status.label}
                </span>
                {result.multifile && result.multifile.files.length > 1 && (
                  <span className="rounded border border-sky-500/30 bg-sky-950/80 px-2.5 py-1 font-mono text-xs text-sky-300">
                    Validated {result.multifile.files.length} files
                  </span>
                )}
              </div>

              {partial && (
                <div className="mt-3 rounded-lg border border-amber-500/40 bg-amber-950/40 p-3 text-sm text-amber-200">
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

              <h2 className="mt-6 font-mono text-base font-semibold uppercase tracking-wider text-white">Diagnostics</h2>
              {result.diagnostics.length === 0 && (
                <p className="mt-2 text-sm text-slate-400 font-mono">No issues found.</p>
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
                      className={`rounded-lg border p-3.5 text-sm transition-colors ${s.card} ${clickable ? 'cursor-pointer' : ''} ${activeDiagnostic === i ? 'ring-2 ring-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.3)]' : ''}`}
                    >
                      <div className={`font-mono text-xs font-semibold uppercase tracking-wide ${s.title}`}>
                        {d.severity.toUpperCase()} · {d.code}
                        {where && ` · ${where}`}
                      </div>
                      <div className="mt-1 text-slate-200">{d.message}</div>
                      {clickable && (
                        <div className="mt-1.5 font-mono text-[11px] text-sky-400/80">
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
                <h2 className="mt-6 font-mono text-base font-semibold uppercase tracking-wider text-white">Suggested fixes</h2>
              )}
              {result.recommendations.map(r => (
                <div key={r.id} className="mt-2.5 rounded-lg border border-sky-500/30 bg-sky-950/40 p-3.5 text-sm text-slate-200">
                  <div className="font-mono text-xs font-semibold uppercase tracking-wide text-cyan-300">{r.title}</div>
                  <div className="mt-1 text-slate-300">{r.explanation}</div>
                  {r.proposed_change && (
                    <div className="mt-2">
                      <div className="text-slate-300">
                        <span className="font-semibold text-white">Suggested change:</span>{' '}
                        {r.proposed_change.description}
                      </div>
                      {r.proposed_change.preview !== null && (
                        <pre className="mt-2 overflow-x-auto rounded-lg border border-slate-800 bg-slate-950 p-2.5 font-mono text-xs text-emerald-400">
                          {r.proposed_change.preview}
                        </pre>
                      )}
                    </div>
                  )}
                  {r.fix_kind === 'judgment' && (
                    <div className="mt-2 font-mono text-[11px] text-slate-400">
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
