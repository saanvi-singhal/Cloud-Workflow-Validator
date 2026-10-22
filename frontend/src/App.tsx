import { useRef, useState, type ChangeEvent } from 'react';
import type { AnalysisResult, Diagnostic, SourceFormat } from './types';
import { analyze } from './api';
import { diffResults } from './graphDiff';
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
import terraformSample from './samples/main.tf?raw';
import dockerfileSample from './samples/Dockerfile?raw';
import yamlSample from './samples/ci.yml?raw';

// The same files are used to generate the mocks (frontend/scripts/generate_mocks.py).
const SAMPLES: Record<SourceFormat, string> = {
  terraform: terraformSample,
  dockerfile: dockerfileSample,
  yaml: yamlSample,
};

const STATUS_STYLES: Record<StatusTone, string> = {
  valid: 'bg-green-100 text-green-800 ring-1 ring-green-300',
  warning: 'bg-amber-100 text-amber-800 ring-1 ring-amber-300',
  error: 'bg-red-100 text-red-800 ring-1 ring-red-300',
};

const FEATURES = [
  {
    step: '1',
    title: 'Dependency graph',
    text: 'See how every resource, stage or task connects.',
    style: 'border-indigo-500 bg-indigo-50',
    badge: 'bg-indigo-600',
  },
  {
    step: '2',
    title: 'Issue detection',
    text: 'Catch cycles and missing references before deploying.',
    style: 'border-rose-500 bg-rose-50',
    badge: 'bg-rose-600',
  },
  {
    step: '3',
    title: 'Suggested fixes',
    text: 'Get clear recommendations with a preview of the change.',
    style: 'border-emerald-500 bg-emerald-50',
    badge: 'bg-emerald-600',
  },
];

const SEVERITY_STYLES: Record<string, { card: string; title: string }> = {
  error: {
    card: 'border-red-300 bg-red-50 hover:bg-red-100',
    title: 'text-red-700',
  },
  warning: {
    card: 'border-amber-300 bg-amber-50 hover:bg-amber-100',
    title: 'text-amber-700',
  },
  info: {
    card: 'border-sky-300 bg-sky-50 hover:bg-sky-100',
    title: 'text-sky-700',
  },
};

type View = 'editor' | 'results';

function detectLanguage(fileName: string): SourceFormat | null {
  const name = fileName.toLowerCase();
  if (name.endsWith('.tf')) return 'terraform';
  if (name.startsWith('dockerfile') || name.endsWith('.dockerfile')) return 'dockerfile';
  if (name.endsWith('.yml') || name.endsWith('.yaml')) return 'yaml';
  return null;
}

export default function App() {
  const [language, setLanguage] = useState<SourceFormat>('terraform');
  const [code, setCode] = useState('');
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fileName, setFileName] = useState('');
  const [uploadNote, setUploadNote] = useState('');
  const [view, setView] = useState<View>('editor');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState<ReadonlySet<string>>(new Set());
  const [activeDiagnostic, setActiveDiagnostic] = useState<number | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [oldCode, setOldCode] = useState('');
  const [newCode, setNewCode] = useState('');
  const [oldResult, setOldResult] = useState<AnalysisResult | null>(null);
  const [newResult, setNewResult] = useState<AnalysisResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const topRef = useRef<HTMLDivElement>(null);

  async function handleAnalyze() {
    if (code.trim() === '') {
      setResult(null);
      setError('Please paste some code, load a sample or upload a file first.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);
    selectNode(null);

    try {
      const data = await analyze(language, code, fileName || undefined);
      setResult(data);
      setView('results');
      topRef.current?.scrollIntoView?.({ behavior: 'smooth' });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  async function handleCompare() {
    if (!oldCode.trim() || !newCode.trim()) {
      setCompareError('Enter both the old and new configurations first.');
      return;
    }

    setCompareLoading(true);
    setCompareError('');
    setOldResult(null);
    setNewResult(null);

    try {
      const [oldData, newData] = await Promise.all([
        analyze(language, oldCode),
        analyze(language, newCode),
      ]);
      setOldResult(oldData);
      setNewResult(newData);
      setView('results');
      topRef.current?.scrollIntoView?.({ behavior: 'smooth' });
    } catch (err) {
      setCompareError(
        err instanceof Error ? err.message : 'Comparison failed. Please try again.',
      );
    } finally {
      setCompareLoading(false);
    }
  }

  async function handleFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    const text = await file.text();
    setCode(text);
    setFileName(file.name);
    setResult(null);
    setError('');

    const detected = detectLanguage(file.name);
    if (detected) {
      setLanguage(detected);
      setUploadNote('');
    } else {
      setUploadNote("Couldn't tell the format from the file name. Please choose it above.");
    }

    e.target.value = '';
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

  function jumpTo(location: Diagnostic['source_location']) {
    const el = textareaRef.current;
    const range = selectionRange(code, location);
    if (!el || !range || location?.start_line == null) return;
    el.focus();
    el.setSelectionRange(range.start, range.end); // end_column is exclusive, like this API
    el.scrollTop = Math.max(0, (location.start_line - 3) * 20);
  }

  // Goes back to the editor page, then selects the location once it is visible.
  function showInEditor(location: Diagnostic['source_location']) {
    setView('editor');
    setTimeout(() => jumpTo(location), 0);
  }

  const status = result ? getStatus(result) : null;
  const selectedNode = result?.graph.nodes.find(n => n.id === selectedNodeId) ?? null;
  const partial = result ? isPartial(result) : false;
  const hasFixes = (result?.recommendations.length ?? 0) > 0;
  const graphDiff = oldResult && newResult ? diffResults(oldResult, newResult) : null;

  return (
    <div className="min-h-screen w-full bg-linear-to-b from-indigo-50 via-slate-50 to-white text-slate-900">
      <div ref={topRef} />
      <header
        className={`w-full bg-linear-to-r from-indigo-600 via-purple-600 to-pink-500 px-4 text-center text-white shadow-lg ${
          view === 'results' ? 'py-6' : 'py-14'
        }`}
      >
        <h1 className="text-4xl font-extrabold tracking-tight">Cloud Workflow Validator</h1>
        <p className="mx-auto mt-3 max-w-xl text-lg text-indigo-50">
          Analyze configuration dependencies before deployment.
        </p>
      </header>

      {/* ---------------- Page 1: the editor ---------------- */}
      <main className={`w-full px-4 py-6 ${view === 'editor' ? '' : 'hidden'}`}>
        <div className="mb-6 grid gap-4 sm:grid-cols-3">
          {FEATURES.map(f => (
            <div key={f.title} className={`rounded-xl border-t-4 p-5 shadow-sm ${f.style}`}>
              <span
                className={`inline-flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold text-white ${f.badge}`}
              >
                {f.step}
              </span>
              <h3 className="mt-2 text-lg font-bold text-slate-900">{f.title}</h3>
              <p className="mt-1 text-base text-slate-700">{f.text}</p>
            </div>
          ))}
        </div>

        <section className="w-full rounded-2xl bg-white p-5 shadow-lg ring-1 ring-indigo-100 sm:p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <label className="text-base font-semibold text-slate-800">
              Input format
              <select
                value={language}
                onChange={e => setLanguage(e.target.value as SourceFormat)}
                className="mt-1 block w-56 rounded-lg border-2 border-indigo-200 bg-white p-2.5 text-base font-normal focus:border-indigo-500 focus:outline-none"
              >
                <option value="terraform">Terraform</option>
                <option value="dockerfile">Dockerfile</option>
                <option value="yaml">YAML</option>
              </select>
            </label>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => fileInputRef.current?.click()}
                className="rounded-lg border-2 border-indigo-500 bg-white px-5 py-2 text-base font-semibold text-indigo-700 shadow-sm hover:bg-indigo-50"
              >
                Upload file
              </button>
              <button
                onClick={() => {
                  setCode(SAMPLES[language]);
                  setFileName('');
                  setUploadNote('');
                  setError('');
                }}
                className="rounded-lg bg-emerald-500 px-5 py-2 text-base font-semibold text-white shadow-sm hover:bg-emerald-600"
              >
                Load sample
              </button>
            </div>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".tf,.yml,.yaml,.dockerfile,Dockerfile,*"
            onChange={handleFile}
            className="hidden"
          />

          {fileName && <p className="mt-3 text-sm text-slate-600">Loaded file: {fileName}</p>}
          {uploadNote && <p className="mt-1 text-sm text-amber-700">{uploadNote}</p>}

          {compareMode ? (
            <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div>
                <label className="mb-2 block font-bold text-red-700">Old Version</label>
                <textarea
                  value={oldCode}
                  onChange={e => setOldCode(e.target.value)}
                  placeholder="Paste the old configuration here"
                  rows={18}
                  spellCheck={false}
                  className="w-full rounded-lg border-2 border-red-200 bg-slate-50 p-4 font-mono text-sm leading-5 focus:border-red-400 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-2 block font-bold text-green-700">New Version</label>
                <textarea
                  value={newCode}
                  onChange={e => setNewCode(e.target.value)}
                  placeholder="Paste the new configuration here"
                  rows={18}
                  spellCheck={false}
                  className="w-full rounded-lg border-2 border-green-200 bg-slate-50 p-4 font-mono text-sm leading-5 focus:border-green-400 focus:outline-none"
                />
              </div>
            </div>
          ) : (
            <textarea
              ref={textareaRef}
              value={code}
              onChange={e => setCode(e.target.value)}
              placeholder="Paste your configuration here, or upload a file"
              rows={18}
              spellCheck={false}
              className="mt-4 w-full rounded-lg border-2 border-indigo-200 bg-slate-50 p-4 font-mono text-base leading-5 text-slate-900 focus:border-indigo-500 focus:outline-none"
            />
          )}

          <div className="mt-5 flex flex-wrap items-center gap-4">
            <button
              onClick={() => {
                setCompareMode(value => !value);
                setCompareError('');
                setError('');
              }}
              className="rounded-lg border-2 border-purple-500 bg-white px-5 py-3 font-semibold text-purple-700 hover:bg-purple-50"
            >
              {compareMode ? 'Single Version' : 'Compare Versions'}
            </button>
            {compareMode ? (
              <button
                onClick={handleCompare}
                disabled={compareLoading}
                className="rounded-lg bg-purple-600 px-8 py-3 text-lg font-bold text-white hover:bg-purple-700 disabled:opacity-60"
              >
                {compareLoading ? 'Comparing...' : 'Compare Graphs'}
              </button>
            ) : (
              <button
                onClick={handleAnalyze}
                disabled={loading}
                className="rounded-lg bg-linear-to-r from-indigo-600 to-purple-600 px-8 py-3 text-lg font-bold text-white shadow-md hover:from-indigo-700 hover:to-purple-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Analyzing...' : 'Analyze'}
              </button>
            )}
            {!compareMode && result && (
              <button
                onClick={() => setView('results')}
                className="rounded-lg border-2 border-purple-500 bg-white px-5 py-2.5 text-base font-semibold text-purple-700 hover:bg-purple-50"
              >
                View results
              </button>
            )}
          </div>
          {compareError && <p className="mt-3 text-red-700">{compareError}</p>}
        </section>

        {loading && (
          <section className="mt-6 flex w-full flex-col items-center justify-center rounded-2xl bg-white p-8 text-center shadow-lg ring-1 ring-indigo-100">
            <div className="h-12 w-12 animate-spin rounded-full border-4 border-indigo-100 border-t-indigo-600" />
            <h2 className="mt-4 text-xl font-bold text-slate-900">Analyzing your configuration...</h2>
            <p className="mt-1 text-base text-slate-600">
              Building the dependency graph and checking for issues.
            </p>
          </section>
        )}

        {!loading && error && (
          <section className="mt-6 flex w-full flex-col items-center justify-center rounded-2xl border-2 border-red-300 bg-red-50 p-8 text-center">
            <h2 className="text-xl font-bold text-red-700">Couldn't analyze</h2>
            <p className="mt-1 max-w-lg text-base text-red-700">{error}</p>
          </section>
        )}
      </main>

      {view === 'results' && compareMode && oldResult && newResult && graphDiff && (
        <main className="w-full px-4 py-6">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <button
              onClick={() => setView('editor')}
              className="rounded-lg bg-indigo-600 px-5 py-2.5 font-semibold text-white hover:bg-indigo-700"
            >
              Back to comparison editor
            </button>
            <button
              onClick={() => { setView('editor'); setCompareMode(true); }}
              className="rounded-lg border-2 border-purple-500 bg-white px-5 py-2.5 font-semibold text-purple-700 hover:bg-purple-50"
            >
              Edit versions
            </button>
          </div>

          <section className="mb-6 rounded-2xl bg-white p-5 shadow-lg ring-1 ring-indigo-100">
            <h2 className="text-xl font-bold">Comparison summary</h2>
            <div className="mt-3 flex flex-wrap gap-3 text-sm font-semibold">
              <span className="rounded-lg bg-green-100 px-4 py-2 text-green-800">{graphDiff.addedNodes.length} added nodes</span>
              <span className="rounded-lg bg-red-100 px-4 py-2 text-red-800">{graphDiff.removedNodes.length} removed nodes</span>
              <span className="rounded-lg bg-orange-100 px-4 py-2 text-orange-800">{graphDiff.rewiredNodes.length} rewired resources</span>
              <span className="rounded-lg bg-green-100 px-4 py-2 text-green-800">{graphDiff.addedEdges.length} added edges</span>
              <span className="rounded-lg bg-red-100 px-4 py-2 text-red-800">{graphDiff.removedEdges.length} removed edges</span>
              <span className={`rounded-lg px-4 py-2 ${graphDiff.newCycles.length ? 'bg-red-100 text-red-800' : 'bg-slate-100 text-slate-700'}`}>{graphDiff.newCycles.length} new cycle diagnostics</span>
            </div>
            {graphDiff.newCycles.length > 0 && (
              <div className="mt-4 rounded-lg border border-red-300 bg-red-50 p-3 text-red-800">
                <strong>Warning: new dependency cycle diagnostic(s)</strong>
                <ul className="mt-2 list-disc pl-5">
                  {graphDiff.newCycles.map((cycle, index) => <li key={`${cycle.code}-${index}`}>{cycle.message}</li>)}
                </ul>
              </div>
            )}
            {graphDiff.identical && <p className="mt-3 text-slate-600">No graph changes detected.</p>}
          </section>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <section className="min-w-0 rounded-2xl bg-white p-4 shadow-lg ring-1 ring-red-200">
              <h2 className="mb-3 text-lg font-bold text-red-700">Old Version Graph</h2>
              <DependencyGraph
                result={oldResult}
                highlighted={new Set()}
                onSelectNode={() => {}}
                removedNodeIds={new Set(graphDiff.removedNodes)}
                rewiredNodeIds={new Set(graphDiff.rewiredNodes)}
                removedEdgeKeys={new Set(graphDiff.removedEdges)}
              />
            </section>
            <section className="min-w-0 rounded-2xl bg-white p-4 shadow-lg ring-1 ring-green-200">
              <h2 className="mb-3 text-lg font-bold text-green-700">New Version Graph</h2>
              <DependencyGraph
                result={newResult}
                highlighted={new Set()}
                onSelectNode={() => {}}
                addedNodeIds={new Set(graphDiff.addedNodes)}
                rewiredNodeIds={new Set(graphDiff.rewiredNodes)}
                addedEdgeKeys={new Set(graphDiff.addedEdges)}
              />
            </section>
          </div>

          <section className="mt-6 rounded-2xl bg-white p-5 shadow-lg ring-1 ring-indigo-100">
            <h2 className="text-xl font-bold">Changed resources and dependencies</h2>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <div><h3 className="font-semibold text-green-700">Added nodes</h3>{graphDiff.addedNodes.length ? <ul className="list-disc pl-5">{graphDiff.addedNodes.map(id => <li key={id}>{id}</li>)}</ul> : <p className="text-slate-500">None</p>}</div>
              <div><h3 className="font-semibold text-red-700">Removed nodes</h3>{graphDiff.removedNodes.length ? <ul className="list-disc pl-5">{graphDiff.removedNodes.map(id => <li key={id}>{id}</li>)}</ul> : <p className="text-slate-500">None</p>}</div>
              <div><h3 className="font-semibold text-orange-700">Rewired resources</h3>{graphDiff.rewiredNodes.length ? <ul className="list-disc pl-5">{graphDiff.rewiredNodes.map(id => <li key={id}>{id}</li>)}</ul> : <p className="text-slate-500">None</p>}</div>
              <div><h3 className="font-semibold">Removed dependencies</h3>{graphDiff.removedEdges.length ? <ul className="list-disc pl-5">{graphDiff.removedEdges.map(key => <li key={key}>{key}</li>)}</ul> : <p className="text-slate-500">None</p>}</div>
            </div>
          </section>
        </main>
      )}

      {/* ---------------- Page 2: the big graph and the results ---------------- */}
      {view === 'results' && result && status && !compareMode && (
        <main className="w-full px-4 py-6">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <button
              onClick={() => setView('editor')}
              className="rounded-lg bg-indigo-600 px-5 py-2.5 text-base font-semibold text-white shadow-sm hover:bg-indigo-700"
            >
              Back to editor
            </button>
            <span className={`rounded-full px-5 py-2 text-lg font-bold ${STATUS_STYLES[status.tone]}`}>
              {status.label}
            </span>
          </div>

          {partial && (
            <div className="mb-6 rounded-xl border-2 border-amber-300 bg-amber-50 p-4 text-base text-amber-900">
              <span className="font-bold">Partial analysis.</span> Some constructs could not be
              analysed, so the graph may be missing dependencies. See the unsupported-construct
              warnings below.
            </div>
          )}

          <div className="grid gap-6 xl:grid-cols-3">
            <section className="rounded-2xl bg-white p-5 shadow-lg ring-1 ring-indigo-100 xl:col-span-2">
              <DependencyGraph
                result={result}
                highlighted={highlighted}
                onSelectNode={selectNode}
              />
            </section>

            <aside>
              {selectedNode ? (
                <NodeDetails
                  result={result}
                  node={selectedNode}
                  onJump={location => showInEditor(location)}
                  onSelectDiagnostic={selectDiagnostic}
                  onClose={() => selectNode(null)}
                />
              ) : (
                <div className="flex min-h-48 items-center justify-center rounded-2xl border-2 border-dashed border-indigo-300 bg-white/70 p-6 text-center text-base text-slate-600">
                  Select a box in the graph to inspect it here.
                </div>
              )}
            </aside>
          </div>

          <div className={`mt-6 grid gap-6 ${hasFixes ? 'lg:grid-cols-2' : ''}`}>
            <section className="rounded-2xl bg-white p-5 shadow-lg ring-1 ring-indigo-100">
              <h2 className="text-xl font-bold text-slate-900">Diagnostics</h2>
              {result.diagnostics.length === 0 && (
                <p className="mt-2 text-base text-slate-600">No issues found.</p>
              )}
              <ul className="mt-3 space-y-3">
                {result.diagnostics.map((d, i) => {
                  const s = SEVERITY_STYLES[d.severity] ?? SEVERITY_STYLES.info;
                  const where = formatLocation(d.source_location);
                  const linked = diagnosticNodeIds(result, i).length > 0;
                  const clickable = where !== null || linked;
                  return (
                    <li
                      key={i}
                      onClick={clickable ? () => selectDiagnostic(i) : undefined}
                      className={`rounded-lg border-2 p-4 text-base ${s.card} ${clickable ? 'cursor-pointer' : ''} ${activeDiagnostic === i ? 'ring-2 ring-indigo-500' : ''}`}
                    >
                      <div className={`font-bold ${s.title}`}>
                        {d.severity.toUpperCase()} · {d.code}
                        {where && ` · ${where}`}
                      </div>
                      <div className="mt-1 text-slate-800">{d.message}</div>
                      {clickable && (
                        <div className="mt-2 text-sm text-slate-600">
                          {where && linked
                            ? 'Click to show it in the editor and the graph'
                            : where
                              ? 'Click to jump to this location'
                              : 'Click to show it in the graph'}
                        </div>
                      )}
                      {where && (
                        <button
                          onClick={e => {
                            e.stopPropagation();
                            showInEditor(d.source_location);
                          }}
                          className="mt-2 rounded-md bg-white px-3 py-1 text-sm font-semibold text-indigo-700 ring-1 ring-indigo-300 hover:bg-indigo-50"
                        >
                          Show in editor
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>

            {hasFixes && (
              <section className="rounded-2xl bg-white p-5 shadow-lg ring-1 ring-indigo-100">
                <h2 className="text-xl font-bold text-slate-900">Suggested fixes</h2>
                {result.recommendations.map(r => (
                  <div
                    key={r.id}
                    className="mt-3 rounded-lg border-2 border-indigo-200 bg-indigo-50 p-4 text-base"
                  >
                    <div className="text-lg font-bold text-indigo-900">{r.title}</div>
                    <div className="mt-1 text-slate-800">{r.explanation}</div>
                    {r.proposed_change && (
                      <div className="mt-3">
                        <div className="text-slate-800">
                          <span className="font-semibold">Suggested change:</span>{' '}
                          {r.proposed_change.description}
                        </div>
                        {r.proposed_change.preview !== null && (
                          <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-sm text-green-300">
                            {r.proposed_change.preview}
                          </pre>
                        )}
                      </div>
                    )}
                    {r.fix_kind === 'judgment' && (
                      <div className="mt-3 text-sm text-slate-600">
                        Review before applying: this tool never changes your files.
                      </div>
                    )}
                  </div>
                ))}
              </section>
            )}
          </div>
        </main>
      )}
    </div>
  );
}