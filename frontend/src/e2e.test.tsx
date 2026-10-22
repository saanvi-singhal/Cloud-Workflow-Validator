// @vitest-environment jsdom
// End-to-end check against a RUNNING backend (not mocks): every example in
// examples/ and every frontend sample is entered in the real UI, submitted to
// the API, and the page must show what the backend returned and what the
// example documents. Opt-in, because it needs the backend:
//
//   (cd backend && uvicorn app.main:app --port 8000) &
//   E2E=1 npm test -- e2e
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import App from './App';
import { executionOrderNote, getStatus, isPartial, labelFor } from './analysis';
import type { AnalysisResult, SourceFormat } from './types';

const API = 'http://localhost:8000/api/v1/validate';
const enabled = Boolean((import.meta.env as Record<string, unknown>).E2E);

const examples = import.meta.glob('../../examples/*/*', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;
const samples = import.meta.glob('./samples/*', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

// Documented outcome of each input (examples/README.md): valid, and a
// diagnostic code that must be shown (null = no diagnostics at all).
const EXPECTED: Record<string, [boolean, string | null]> = {
  'yaml/valid_pipeline.yml': [true, null],
  'yaml/unresolved_needs.yml': [false, 'UNRESOLVED_DEPENDENCY'],
  'yaml/cyclic_needs.yml': [false, 'DEPENDENCY_CYCLE'],
  'yaml/schema_errors.yml': [false, 'YAML_SYNTAX_ERROR'],
  'yaml/script_injection.yml': [true, 'SECURITY_RULE_VIOLATION'],
  'dockerfile/multi_stage.Dockerfile': [true, null],
  'dockerfile/unused_stage.Dockerfile': [true, 'UNREACHABLE_NODE'],
  'dockerfile/copy_from_typo.Dockerfile': [true, 'UNRESOLVED_DEPENDENCY'],
  'dockerfile/best_practices.Dockerfile': [false, 'SECURITY_RULE_VIOLATION'],
  'dockerfile/syntax_errors.Dockerfile': [false, 'DOCKERFILE_SYNTAX_ERROR'],
  'terraform/valid_network.tf': [true, null],
  'terraform/depends_on.tf': [true, null],
  'terraform/dynamic_blocks.tf': [true, null],
  'terraform/cyclic.tf': [false, 'DEPENDENCY_CYCLE'],
  'terraform/unresolved_reference.tf': [false, 'UNRESOLVED_DEPENDENCY'],
  'terraform/unsupported_expression.tf': [true, 'UNSUPPORTED_CONSTRUCT'],
  'terraform/security_findings.tf': [true, 'SECURITY_RULE_VIOLATION'],
  'samples/main.tf': [false, 'UNRESOLVED_DEPENDENCY'],
  'samples/ci.yml': [true, null],
  'samples/Dockerfile': [true, 'UNREACHABLE_NODE'],
};

const FORMAT_BY_DIR: Record<string, SourceFormat> = {
  yaml: 'yaml',
  dockerfile: 'dockerfile',
  terraform: 'terraform',
};

function formatOf(name: string): SourceFormat {
  if (name.startsWith('samples/')) {
    if (name.endsWith('.tf')) return 'terraform';
    if (name.endsWith('.yml')) return 'yaml';
    return 'dockerfile';
  }
  return FORMAT_BY_DIR[name.split('/')[0]];
}

const CASES: [string, string][] = [
  ...Object.entries(examples).map(([path, text]) => [path.replace('../../examples/', ''), text]),
  ...Object.entries(samples).map(([path, text]) => [path.replace('./', ''), text]),
] as [string, string][];

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(cleanup);

/** The cards listed under a results heading ("Diagnostics", "Suggested fixes"). */
function cardsUnder(heading: string): HTMLElement[] {
  const title = screen.queryByRole('heading', { level: 2, name: heading });
  if (!title) return [];
  const cards: HTMLElement[] = [];
  let node = title.nextElementSibling;
  while (node && node.tagName !== 'H2') {
    if (node.tagName === 'UL') cards.push(...(Array.from(node.children) as HTMLElement[]));
    else if (node.tagName === 'DIV') cards.push(node as HTMLElement);
    node = node.nextElementSibling;
  }
  return cards;
}

describe.skipIf(!enabled)('frontend shows the backend result for every sample input', () => {
  it('covers every example and sample', () => {
    expect(CASES.map(([name]) => name).sort()).toEqual(Object.keys(EXPECTED).sort());
  });

  it.each(CASES)('%s', async (name, source) => {
    const format = formatOf(name);
    // What the backend says for this input (the UI must show exactly this).
    const response = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, format }),
    });
    expect(response.status).toBe(200);
    const result = (await response.json()) as AnalysisResult;
    const [valid, code] = EXPECTED[name];
    expect(result.valid).toBe(valid);
    if (code) expect(result.diagnostics.map(d => d.code)).toContain(code);
    else expect(result.diagnostics).toEqual([]);

    render(<App />);
    fireEvent.change(screen.getByLabelText('Input format'), { target: { value: format } });
    fireEvent.change(screen.getByPlaceholderText(/Paste your/), {
      target: { value: source },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }));

    // Status badge.
    const status = getStatus(result);
    expect(await screen.findByText(status.label, {}, { timeout: 5000 })).toBeTruthy();
    expect(status.label === 'Invalid').toBe(!valid);

    // Every diagnostic, in order, with its severity and code.
    const diagnostics = cardsUnder('Diagnostics');
    expect(diagnostics).toHaveLength(result.diagnostics.length);
    result.diagnostics.forEach((d, i) => {
      const card = within(diagnostics[i]);
      expect(card.getByText(d.message)).toBeTruthy();
      expect(diagnostics[i].textContent).toContain(`${d.severity.toUpperCase()} · ${d.code}`);
    });
    if (result.diagnostics.length === 0) expect(screen.getByText('No issues found.')).toBeTruthy();

    // Every recommendation, with its preview when there is one.
    const fixes = cardsUnder('Suggested fixes');
    expect(fixes).toHaveLength(result.recommendations.length);
    result.recommendations.forEach((r, i) => {
      expect(fixes[i].textContent).toContain(r.title);
      if (r.proposed_change?.preview) {
        expect(fixes[i].querySelector('pre')?.textContent).toBe(r.proposed_change.preview);
      }
    });

    // Execution order, or the reason it is missing.
    if (result.execution_order) {
      result.execution_order.forEach((id, i) => {
        expect(screen.getByText(`${i + 1}. ${labelFor(result, id)}`)).toBeTruthy();
      });
    } else {
      expect(screen.getByText(executionOrderNote(result)!)).toBeTruthy();
    }

    // Partial-analysis banner exactly when the backend reports partial analysis.
    expect(Boolean(screen.queryByText('Partial analysis.'))).toBe(isPartial(result));

    // An empty graph is explained instead of shown blank.
    expect(Boolean(screen.queryByText('Nothing to draw'))).toBe(result.graph.nodes.length === 0);
  });
});
