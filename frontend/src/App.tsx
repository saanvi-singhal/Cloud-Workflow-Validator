import { useRef, useState, type ChangeEvent } from 'react';
import type { AnalysisResult } from './types';
import { analyze } from './api';
import DependencyGraph from './components/DependencyGraph';

const SAMPLES: Record<string, string> = {
  terraform: `resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "app" {
  vpc_id = aws_vpc.main.id
  tags   = { vpc = aws_vpc.mian.id }
}`,
  dockerfile: `FROM node:20 AS build
WORKDIR /app
COPY . .
RUN npm ci && npm run build

FROM nginx:latest
COPY --from=build /app/dist /usr/share/nginx/html`,
  yaml: `tasks:
  build:
    run: npm run build
  test:
    needs: [build]
    run: npm test
  deploy:
    needs: [test]
    run: ./deploy.sh`,
};

const FEATURES = [
  { icon: '🕸️', title: 'Dependency graph', text: 'See how every resource, stage or task connects.' },
  { icon: '🔍', title: 'Issue detection', text: 'Catch cycles and missing references before deploying.' },
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

function detectLanguage(fileName: string): string | null {
  const name = fileName.toLowerCase();
  if (name.endsWith('.tf')) return 'terraform';
  if (name.startsWith('dockerfile') || name.endsWith('.dockerfile')) return 'dockerfile';
  if (name.endsWith('.yml') || name.endsWith('.yaml')) return 'yaml';
  return null;
}

function getStatus(result: AnalysisResult) {
  const hasError = result.diagnostics.some(d => d.severity === 'error');
  if (hasError) return { label: 'Issues found', style: 'bg-red-100 text-red-700' };
  if (result.diagnostics.length > 0) return { label: 'Warnings', style: 'bg-amber-100 text-amber-700' };
  return { label: 'Valid', style: 'bg-green-100 text-green-700' };
}

export default function App() {
  const [language, setLanguage] = useState('terraform');
  const [code, setCode] = useState('');
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fileName, setFileName] = useState('');
  const [uploadNote, setUploadNote] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleAnalyze() {
    if (code.trim() === '') {
      setResult(null);
      setError('Please paste some code, load a sample or upload a file first.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const data = await analyze(language, code);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setLoading(false);
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

  function jumpToLine(line: number) {
    const el = textareaRef.current;
    if (!el) return;
    const lines = code.split('\n');
    const start = lines
      .slice(0, line - 1)
      .reduce((sum, l) => sum + l.length + 1, 0);
    const end = start + (lines[line - 1]?.length ?? 0);
    el.focus();
    el.setSelectionRange(start, end);
    el.scrollTop = Math.max(0, (line - 3) * 20);
  }

  const status = result ? getStatus(result) : null;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-linear-to-r from-slate-900 via-indigo-900 to-slate-900 px-8 py-12 text-center text-white">
        <h1 className="text-4xl font-bold">Cloud Workflow Analyzer</h1>
        <p className="mx-auto mt-3 max-w-xl text-lg text-indigo-100">
          Analyze configuration dependencies before deployment.
        </p>
      </header>

      <main className="mx-auto max-w-6xl p-8">
        <div className="mb-8 grid gap-4 sm:grid-cols-3">
          {FEATURES.map(f => (
            <div key={f.title} className="rounded-xl bg-white p-5 shadow-sm">
              <div className="text-2xl">{f.icon}</div>
              <h3 className="mt-2 font-semibold text-slate-900">{f.title}</h3>
              <p className="mt-1 text-sm text-slate-600">{f.text}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <section className="rounded-xl bg-white p-6 shadow">
            <div className="flex items-end justify-between">
              <label className="text-sm font-medium text-slate-700">
                Input format
                <select
                  value={language}
                  onChange={e => setLanguage(e.target.value)}
                  className="mt-1 block w-48 rounded-md border border-slate-300 p-2"
                >
                  <option value="terraform">Terraform</option>
                  <option value="dockerfile">Dockerfile</option>
                  <option value="yaml">YAML</option>
                </select>
              </label>
              <div className="flex gap-4 text-sm font-medium">
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="text-indigo-600 hover:underline"
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
                  className="text-indigo-600 hover:underline"
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

            {fileName && (
              <p className="mt-3 text-xs text-slate-500">Loaded file: {fileName}</p>
            )}
            {uploadNote && (
              <p className="mt-1 text-xs text-amber-600">{uploadNote}</p>
            )}

            <textarea
              ref={textareaRef}
              value={code}
              onChange={e => setCode(e.target.value)}
              placeholder="Paste your configuration here, or upload a file"
              rows={14}
              spellCheck={false}
              className="mt-4 w-full rounded-md border border-slate-300 p-3 font-mono text-sm leading-5"
            />

            <button
              onClick={handleAnalyze}
              disabled={loading}
              className="mt-4 rounded-md bg-indigo-600 px-5 py-2 font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? 'Analyzing...' : 'Analyze'}
            </button>
          </section>

          {loading ? (
            <section className="flex min-h-80 flex-col items-center justify-center rounded-xl bg-white p-6 text-center shadow">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-indigo-600" />
              <h2 className="mt-4 text-lg font-semibold text-slate-800">Analyzing your configuration...</h2>
              <p className="mt-1 text-sm text-slate-500">Building the dependency graph and checking for issues.</p>
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
                Choose a format, load a sample, upload a file or paste your own code, then click Analyze.
              </p>
            </section>
          ) : (
            <section className="rounded-xl bg-white p-6 shadow">
              <span className={`rounded-full px-3 py-1 text-sm font-semibold ${status.style}`}>
                {status.label}
              </span>

              {result.graph && <DependencyGraph result={result} />}

              <h2 className="mt-4 font-semibold text-slate-900">Diagnostics</h2>
              {result.diagnostics.length === 0 && (
                <p className="mt-2 text-sm text-slate-500">No issues found.</p>
              )}
              <ul className="mt-2 space-y-2">
                {result.diagnostics.map((d, i) => {
                  const s = SEVERITY_STYLES[d.severity] ?? SEVERITY_STYLES.info;
                  return (
                    <li
                      key={i}
                      onClick={() => jumpToLine(d.source_location.start_line)}
                      className={`cursor-pointer rounded-md border p-3 text-sm ${s.card}`}
                    >
                      <div className={`font-semibold ${s.title}`}>
                        {d.severity.toUpperCase()} · {d.code} · line {d.source_location.start_line}
                      </div>
                      <div className="mt-1 text-slate-700">{d.message}</div>
                      <div className="mt-1 text-xs text-slate-500">Click to jump to this line</div>
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
                  {r.proposed_change?.preview ? (
  <pre className="mt-2 rounded bg-slate-900 p-2 text-xs text-green-300">
    {r.proposed_change.preview}
  </pre>
) : (
  r.proposed_change && (
    <p className="mt-2 text-xs text-slate-600">{r.proposed_change.description}</p>
  )
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