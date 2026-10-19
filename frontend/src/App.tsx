import { useState } from 'react';

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

export default function App() {
  const [language, setLanguage] = useState('terraform');
  const [code, setCode] = useState('');

  function handleAnalyze() {
    console.log('Language:', language);
    console.log('Code:', code);
  }

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
              <button
                onClick={() => setCode(SAMPLES[language])}
                className="text-sm font-medium text-indigo-600 hover:underline"
              >
                Load sample
              </button>
            </div>

            <textarea
              value={code}
              onChange={e => setCode(e.target.value)}
              placeholder="Paste your configuration here"
              rows={14}
              className="mt-4 w-full rounded-md border border-slate-300 p-3 font-mono text-sm"
            />

            <button
              onClick={handleAnalyze}
              className="mt-4 rounded-md bg-indigo-600 px-5 py-2 font-semibold text-white hover:bg-indigo-700"
            >
              Analyze
            </button>
          </section>

          <section className="flex min-h-80 flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 bg-white/60 p-6 text-center">
            <div className="text-5xl">🕸️</div>
            <h2 className="mt-3 text-lg font-semibold text-slate-800">
              Your dependency graph will appear here
            </h2>
            <p className="mt-1 max-w-xs text-sm text-slate-500">
              Choose a format, load a sample or paste your own code, then click Analyze.
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}