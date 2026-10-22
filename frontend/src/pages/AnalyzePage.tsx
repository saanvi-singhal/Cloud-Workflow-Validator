import { useMemo, useRef, useState, type ChangeEvent } from 'react';
import type { AnalysisResult, Diagnostic, FileItem, SourceFormat, SourceLocation } from '../types';
import { analyze, analyzeMultiFile } from '../api';
import {
  diagnosticNodeIds,
  isPartial,
  selectionRange,
  severityCounts,
  verdict,
  type StatusTone,
} from '../analysis';
import { blastRadius } from '../blastRadius';
import DependencyGraph from '../components/DependencyGraph';
import NodeDetails from '../components/NodeDetails';
import MultiFilePanel from '../components/MultiFilePanel';
import AdvisorPanel from '../components/AdvisorPanel';
import { advisorItems } from '../advisor';
import IssuesList from '../components/IssuesList';
import { FILE_EXTENSION, MIXED_SAMPLE, MULTIFILE_TERRAFORM_SAMPLE, SAMPLES } from '../sampleFiles';

const FORMATS: { value: SourceFormat; label: string }[] = [
  { value: 'terraform', label: 'Terraform' },
  { value: 'yaml', label: 'GitHub Actions' },
  { value: 'dockerfile', label: 'Dockerfile' },
  { value: 'mixed', label: 'Mixed' },
];

const VERDICT_STYLE: Record<StatusTone, { rule: string; title: string }> = {
  error: { rule: 'bg-error', title: 'text-error' },
  warning: { rule: 'bg-warning', title: 'text-warning' },
  valid: { rule: 'bg-ok', title: 'text-ok' },
};

type Tab = 'issues' | 'graph' | 'files' | 'advisor';

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

function asFiles(samples: { name: string; content: string }[]): FileItem[] {
  return samples.map((s, i) => ({
    id: String(Date.now() + i),
    name: s.name,
    content: s.content,
  }));
}

export default function AnalyzePage() {
  const [language, setLanguage] = useState<SourceFormat>('terraform');
  const [files, setFiles] = useState<FileItem[]>([{ id: '1', name: '', content: '' }]);
  const [activeFileId, setActiveFileId] = useState<string>('1');
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState<ReadonlySet<string>>(new Set());
  const [activeDiagnostic, setActiveDiagnostic] = useState<number | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [showBlast, setShowBlast] = useState(false);
  const [tab, setTab] = useState<Tab>('issues');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLElement>(null);

  const activeFile = files.find(f => f.id === activeFileId) ?? files[0];
  const code = activeFile?.content ?? '';
  const isMultiFile = files.length > 1;

  function updateActiveFileContent(newContent: string) {
    setFiles(prev => prev.map(f => (f.id === activeFileId ? { ...f, content: newContent } : f)));
  }

  function resetResult() {
    setResult(null);
    setError('');
    selectNode(null);
  }

  async function runAnalysis(toAnalyse: FileItem[], format: SourceFormat) {
    if (!toAnalyse.some(f => f.content.trim() !== '')) {
      setResult(null);
      setError('Paste a configuration, upload files or try a sample first.');
      return;
    }
    setLoading(true);
    resetResult();
    try {
      // Mixed always sends files: the backend detects each one's format.
      const data =
        toAnalyse.length > 1 || format === 'mixed'
          ? await analyzeMultiFile(
              format,
              toAnalyse.map((f, i) => ({
                filename: f.name || `file_${i + 1}${FILE_EXTENSION[format]}`,
                content: f.content,
              })),
            )
          : await analyze(format, toAnalyse[0].content, toAnalyse[0].name || undefined);
      setResult(data);
      setTab(data.diagnostics.length > 0 ? 'issues' : 'graph');
      // On narrow screens the results are below the editor: bring them into view.
      if (window.matchMedia?.('(max-width: 1023px)').matches) {
        setTimeout(() => resultsRef.current?.scrollIntoView?.({ behavior: 'smooth' }), 0);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The analysis failed. Try again.');
    } finally {
      setLoading(false);
    }
  }

  function load(samples: { name: string; content: string }[], format: SourceFormat, message = '') {
    const loaded = asFiles(samples);
    setLanguage(format);
    setFiles(loaded);
    setActiveFileId(loaded[0].id);
    setNote(message);
    resetResult();
    return loaded;
  }

  function loadSample() {
    if (language === 'mixed') {
      load(MIXED_SAMPLE, 'mixed', 'A workflow, a Dockerfile and the two scripts it copies.');
    } else {
      const [first] = load([{ name: '', content: SAMPLES[language] }], language);
      setActiveFileId(first.id);
    }
  }

  function tryExample(format: SourceFormat, multi = false) {
    const samples =
      format === 'mixed'
        ? MIXED_SAMPLE
        : multi
          ? MULTIFILE_TERRAFORM_SAMPLE
          : [{ name: '', content: SAMPLES[format] }];
    const loaded = load(samples, format);
    void runAnalysis(loaded, format);
  }

  async function handleFiles(e: ChangeEvent<HTMLInputElement>) {
    const uploaded = e.target.files;
    if (!uploaded || uploaded.length === 0) return;
    const newFiles: FileItem[] = [];
    for (let i = 0; i < uploaded.length; i++) {
      newFiles.push({
        id: String(Date.now() + i),
        name: uploaded[i].name,
        content: await uploaded[i].text(),
      });
    }
    setFiles(newFiles);
    setActiveFileId(newFiles[0].id);
    resetResult();

    // Scripts and other build-context files (build.sh, package.json) don't
    // name a format; several formats together are analysed as 'mixed'.
    const detected = detectFormats(newFiles.map(f => f.name));
    if (detected) {
      setLanguage(detected);
      const others = newFiles.filter(f => detectLanguage(f.name) === null).length;
      const hasDockerfile = newFiles.some(f => detectLanguage(f.name) === 'dockerfile');
      setNote(
        newFiles.length > 1
          ? (detected === 'mixed'
              ? `${newFiles.length} files of different formats; each is checked by its own parser.`
              : `${newFiles.length} files loaded.`) +
              (hasDockerfile && others > 0
                ? ` ${others} other file(s) are build context: COPY sources and scripts run by RUN are checked.`
                : '')
          : '',
      );
    } else {
      setNote("The format couldn't be told from the file name. Choose it above.");
    }
    e.target.value = '';
  }

  function handleAddFile() {
    const newFile: FileItem = {
      id: String(Date.now()),
      name: `module_${files.length + 1}${FILE_EXTENSION[language]}`,
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
      setNote(`There is already a file named ${name}.`);
      return;
    }
    const renamed = files.map(f => (f.id === id ? { ...f, name } : f));
    setFiles(renamed);
    setNote('');
    // Adding e.g. ci.yml next to a Dockerfile switches to mixed analysis.
    if (detectFormats(renamed.map(f => f.name)) === 'mixed') setLanguage('mixed');
  }

  function handleRemoveFile(id: string) {
    if (files.length <= 1) return;
    const remaining = files.filter(f => f.id !== id);
    setFiles(remaining);
    if (activeFileId === id) setActiveFileId(remaining[0].id);
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
    jumpTo(result.diagnostics[index]?.source_location ?? null);
  }

  function showInGraph(index: number) {
    selectDiagnostic(index);
    setTab('graph');
  }

  function jumpTo(location: Diagnostic['source_location']) {
    if (location?.file) {
      const target = files.find(f => f.name === location.file);
      if (target && target.id !== activeFileId) setActiveFileId(target.id);
    }
    setTimeout(() => {
      const el = textareaRef.current;
      const targetCode =
        files.find(f => (location?.file ? f.name === location.file : f.id === activeFileId))
          ?.content ?? code;
      const range = selectionRange(targetCode, location);
      if (!el || !range || location?.start_line == null) return;
      el.focus();
      el.setSelectionRange(range.start, range.end);
      el.scrollTop = Math.max(0, (location.start_line - 3) * 20);
    }, 50);
  }

  function jumpToFile(filename: string, location?: SourceLocation | null) {
    const target = files.find(f => f.name === filename);
    if (target) setActiveFileId(target.id);
    if (location) jumpTo(location);
  }

  const selectedNode = result?.graph.nodes.find(n => n.id === selectedNodeId) ?? null;
  // Everything downstream of the selected node ("click a node, see what breaks").
  const blast = useMemo(
    () => (result && selectedNodeId ? blastRadius(result, selectedNodeId) : undefined),
    [result, selectedNodeId],
  );

  return (
    <div className="mx-auto grid max-w-[1400px] gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <section aria-label="Configuration" className="min-w-0 lg:sticky lg:top-20 lg:self-start">
        <div className="rounded-lg border border-line bg-surface">
          <div className="border-b border-line-soft p-4">
            <div
              role="radiogroup"
              aria-label="Input format"
              className="grid grid-cols-2 gap-1 rounded-md bg-paper p-1 sm:grid-cols-4"
            >
              {FORMATS.map(f => (
                <button
                  key={f.value}
                  type="button"
                  role="radio"
                  aria-checked={language === f.value}
                  onClick={() => setLanguage(f.value)}
                  className={`rounded px-2 py-1.5 text-sm whitespace-nowrap ${
                    language === f.value
                      ? 'bg-surface font-medium text-ink shadow-[0_0_0_1px_var(--color-line)]'
                      : 'text-muted hover:text-ink'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-end gap-1 border-b border-line-soft px-3 pt-2">
            <div className="flex min-w-0 items-end gap-1 overflow-x-auto">
              {files.map((file, idx) => {
                const isActive = file.id === activeFileId;
                const label = file.name || (files.length === 1 ? 'untitled' : `file_${idx + 1}`);
                const hasErr = result?.diagnostics.some(
                  d => d.source_location?.file === file.name && d.severity === 'error',
                );
                return (
                  <div
                    key={file.id}
                    onClick={() => setActiveFileId(file.id)}
                    className={`group -mb-px flex shrink-0 cursor-pointer items-center gap-1.5 border-b-2 px-2.5 py-2 font-mono text-xs ${
                      isActive
                        ? 'border-accent text-ink'
                        : 'border-transparent text-muted hover:text-ink'
                    }`}
                  >
                    {hasErr && (
                      <span className="h-1.5 w-1.5 rounded-full bg-error" title="Has errors" />
                    )}
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
                        className="w-28 rounded border border-accent bg-surface px-1 font-mono text-xs text-ink"
                      />
                    ) : (
                      <span
                        className="max-w-[140px] truncate"
                        title="Double-click to rename"
                        onDoubleClick={() => setRenamingId(file.id)}
                      >
                        {label}
                      </span>
                    )}
                    {files.length > 1 && (
                      <button
                        type="button"
                        onClick={e => {
                          e.stopPropagation();
                          handleRemoveFile(file.id);
                        }}
                        className="text-faint hover:text-error"
                        aria-label={`Remove ${label}`}
                        title="Remove file"
                      >
                        ×
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            <button
              type="button"
              onClick={handleAddFile}
              className="mb-1 shrink-0 rounded px-2 py-1 text-xs text-accent hover:bg-accent-soft"
              title="Add another file"
            >
              + Add file
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="mb-1 shrink-0 rounded px-2 py-1 text-xs text-accent hover:bg-accent-soft"
            >
              Upload files
            </button>
          </div>

          <textarea
            ref={textareaRef}
            value={code}
            onChange={e => updateActiveFileContent(e.target.value)}
            placeholder={`Paste your ${activeFile.name || FORMATS.find(f => f.value === language)?.label} configuration here`}
            rows={18}
            spellCheck={false}
            aria-label="Configuration source"
            className="block h-64 w-full resize-y border-0 bg-surface p-4 sm:h-auto font-mono text-[13px] leading-5 text-ink placeholder:text-faint focus:outline-none focus-visible:outline-none"
          />

          {note && <p className="border-t border-line-soft px-4 py-2 text-sm text-muted">{note}</p>}

          <div className="flex flex-wrap items-center gap-2 border-t border-line-soft p-3">
            <button
              type="button"
              onClick={() => void runAnalysis(files, language)}
              disabled={loading}
              className="rounded-md bg-accent px-5 py-2 text-sm font-semibold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? 'Analyzing...' : isMultiFile ? `Analyze ${files.length} files` : 'Analyze'}
            </button>
            <button
              type="button"
              onClick={loadSample}
              className="rounded-md px-3 py-2 text-sm text-ink hover:bg-paper"
            >
              Load sample
            </button>
            {language === 'terraform' && (
              <button
                type="button"
                onClick={() => {
                  const loaded = load(
                    MULTIFILE_TERRAFORM_SAMPLE,
                    'terraform',
                    'A module split over variables.tf, main.tf and outputs.tf.',
                  );
                  setActiveFileId(loaded[1].id);
                }}
                className="rounded-md px-3 py-2 text-sm text-ink hover:bg-paper"
              >
                Load multi-file sample
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                updateActiveFileContent('');
                setError('');
                textareaRef.current?.focus();
              }}
              disabled={!code}
              className="ml-auto rounded-md px-3 py-2 text-sm text-muted hover:text-error disabled:opacity-40"
            >
              Clear
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".tf,.yml,.yaml,.dockerfile,Dockerfile,*"
              onChange={handleFiles}
              className="hidden"
            />
          </div>
        </div>
        <p className="mt-2 px-1 text-xs text-faint">
          Files are only read and analysed. Nothing is run, and no cloud provider is contacted.
        </p>
      </section>

      <section ref={resultsRef} aria-label="Results" className="min-w-0 scroll-mt-20">
        {loading ? (
          <div className="rounded-lg border border-line bg-surface p-8">
            <div className="h-1 w-full overflow-hidden rounded bg-line-soft">
              <div className="h-full w-1/3 animate-pulse rounded bg-accent" />
            </div>
            <p className="mt-4 font-medium text-ink">Analyzing your configuration</p>
            <p className="mt-1 text-sm text-muted">
              Building the dependency graph and running the checks.
            </p>
          </div>
        ) : error ? (
          <div role="alert" className="rounded-lg border border-error/30 bg-error-soft p-6">
            <h2 className="font-semibold text-error">Couldn't analyze</h2>
            <p className="mt-1 text-sm text-ink">{error}</p>
          </div>
        ) : result === null ? (
          <StartPanel onTry={tryExample} />
        ) : (
          <Results
            result={result}
            tab={tab}
            onTab={setTab}
            activeDiagnostic={activeDiagnostic}
            onSelectDiagnostic={selectDiagnostic}
            onShowInGraph={showInGraph}
            highlighted={highlighted}
            selectNode={selectNode}
            selectedNode={selectedNode}
            blast={blast}
            showBlast={showBlast}
            onToggleBlast={() => setShowBlast(on => !on)}
            jumpTo={jumpTo}
            jumpToFile={jumpToFile}
          />
        )}
      </section>
    </div>
  );
}

function StartPanel({ onTry }: { onTry: (format: SourceFormat, multi?: boolean) => void }) {
  const examples: {
    label: string;
    detail: string;
    format: SourceFormat;
    multi?: boolean;
  }[] = [
    {
      label: 'A Terraform module with a typo',
      detail: 'Unresolved reference, with a patch',
      format: 'terraform',
    },
    {
      label: 'A Terraform module in three files',
      detail: 'Cross-file variables and dependencies',
      format: 'terraform',
      multi: true,
    },
    {
      label: 'A GitHub Actions workflow',
      detail: 'Job order from needs',
      format: 'yaml',
    },
    {
      label: 'A multi-stage Dockerfile',
      detail: 'Unused stage, build advice',
      format: 'dockerfile',
    },
    {
      label: 'A workflow, Dockerfile and scripts',
      detail: 'Mixed formats checked together',
      format: 'mixed',
    },
  ];
  return (
    <div className="rounded-lg border border-line bg-surface p-6 sm:p-8">
      <h2 className="text-xl font-semibold text-ink">Find out whether it's safe to deploy</h2>
      <p className="mt-2 max-w-prose text-muted">
        Paste a Terraform file, a GitHub Actions workflow or a Dockerfile and choose Analyze. You
        get a verdict, every issue with its fix, and a graph of what depends on what.
      </p>
      <h3 className="mt-6 text-sm font-medium text-ink">Or try an example</h3>
      <ul className="mt-2 divide-y divide-line-soft rounded-md border border-line-soft">
        {examples.map(e => (
          <li key={e.label}>
            <button
              type="button"
              onClick={() => onTry(e.format, e.multi)}
              className="flex w-full flex-col gap-0.5 px-4 py-3 text-left hover:bg-paper sm:flex-row sm:items-baseline sm:justify-between sm:gap-4"
            >
              <span className="font-medium text-ink">{e.label}</span>
              <span className="text-sm text-muted">{e.detail}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface ResultsProps {
  result: AnalysisResult;
  tab: Tab;
  onTab: (tab: Tab) => void;
  activeDiagnostic: number | null;
  onSelectDiagnostic: (index: number) => void;
  onShowInGraph: (index: number) => void;
  highlighted: ReadonlySet<string>;
  selectNode: (id: string | null) => void;
  selectedNode: AnalysisResult['graph']['nodes'][number] | null;
  blast: ReturnType<typeof blastRadius> | undefined;
  showBlast: boolean;
  onToggleBlast: () => void;
  jumpTo: (location: SourceLocation | null) => void;
  jumpToFile: (filename: string, location?: SourceLocation | null) => void;
}

function Results(props: ResultsProps) {
  const { result, tab, onTab } = props;
  const v = verdict(result);
  const style = VERDICT_STYLE[v.tone];
  const counts = severityCounts(result);
  const multi = result.multifile && result.multifile.files.length > 1 ? result.multifile : null;
  const advice = advisorItems(result).length;

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'issues', label: 'Issues', count: result.diagnostics.length },
    { id: 'graph', label: 'Graph', count: result.graph.nodes.length },
    ...(multi ? [{ id: 'files' as Tab, label: 'Files', count: multi.files.length }] : []),
    ...(advice ? [{ id: 'advisor' as Tab, label: 'Build advisor', count: advice }] : []),
  ];
  const current = tabs.some(t => t.id === tab) ? tab : 'issues';

  return (
    <div className="rounded-lg border border-line bg-surface">
      <header className="relative px-6 pt-5 pb-4">
        <span
          aria-hidden="true"
          className={`absolute top-0 left-0 h-1 w-full rounded-t-lg ${style.rule}`}
        />
        <h2 className={`text-2xl font-semibold tracking-tight sm:text-[28px] ${style.title}`}>
          {v.title}
        </h2>
        <p className="mt-1 text-muted">{v.detail}</p>
        {multi && (
          <p className="mt-1 text-sm text-faint">Checked {multi.files.length} files together.</p>
        )}
        {isPartial(result) && (
          <p className="mt-3 rounded-md bg-warning-soft px-3 py-2 text-sm text-ink">
            <span className="font-semibold">Partial analysis.</span> Some constructs could not be
            analysed, so the graph may be missing dependencies.
          </p>
        )}
      </header>

      <div
        role="tablist"
        aria-label="Result views"
        className="flex gap-1 overflow-x-auto border-y border-line-soft px-4"
      >
        {tabs.map(t => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={current === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => onTab(t.id)}
            className={`-mb-px shrink-0 border-b-2 px-3 py-2.5 text-sm ${
              current === t.id
                ? 'border-accent font-medium text-ink'
                : 'border-transparent text-muted hover:text-ink'
            }`}
          >
            {t.label}
            {t.count !== undefined && (
              <span className="ml-1.5 text-faint">
                {t.id === 'issues' && counts.error > 0 ? (
                  <span className="text-error">{t.count}</span>
                ) : (
                  t.count
                )}
              </span>
            )}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id={`panel-${current}`}
        aria-labelledby={`tab-${current}`}
        className="p-4 sm:p-5"
      >
        {current === 'issues' && (
          <IssuesList
            result={result}
            activeDiagnostic={props.activeDiagnostic}
            onSelect={props.onSelectDiagnostic}
            onShowInGraph={props.onShowInGraph}
          />
        )}
        {current === 'graph' && (
          <>
            <DependencyGraph
              result={result}
              highlighted={props.highlighted}
              onSelectNode={props.selectNode}
              blast={props.showBlast ? props.blast : undefined}
            />
            {props.selectedNode && (
              <NodeDetails
                result={result}
                node={props.selectedNode}
                onJump={props.jumpTo}
                onSelectDiagnostic={i => {
                  props.onSelectDiagnostic(i);
                  onTab('issues');
                }}
                onClose={() => props.selectNode(null)}
                blast={props.blast}
                blastShown={props.showBlast}
                onToggleBlast={props.onToggleBlast}
                onSelectNode={props.selectNode}
              />
            )}
          </>
        )}
        {current === 'files' && multi && (
          <MultiFilePanel summary={multi} onJumpToFile={props.jumpToFile} />
        )}
        {current === 'advisor' && (
          <AdvisorPanel
            result={result}
            onSelectDiagnostic={i => {
              props.onSelectDiagnostic(i);
              onTab('issues');
            }}
          />
        )}
      </div>
    </div>
  );
}
