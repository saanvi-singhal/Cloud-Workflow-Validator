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
import { executionOrderNote, isPartial, labelFor, verdict } from './analysis';
import { splitRule } from './advisor';
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

const SEVERITY_LABEL = { error: 'Error', warning: 'Warning', info: 'Suggestion' } as const;

beforeAll(() => {
  window.scrollTo = (() => {}) as typeof window.scrollTo;
});

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
    const formats = within(screen.getByRole('radiogroup', { name: 'Input format' }));
    const label = { yaml: 'GitHub Actions', dockerfile: 'Dockerfile', terraform: 'Terraform', mixed: 'Mixed' };
    fireEvent.click(formats.getByRole('radio', { name: label[format] }));
    fireEvent.change(screen.getByLabelText('Configuration source'), { target: { value: source } });
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }));

    // The verdict.
    const v = verdict(result);
    expect(await screen.findByRole('heading', { name: v.title }, { timeout: 5000 })).toBeTruthy();
    expect(v.tone === 'error').toBe(!valid);
    expect(screen.getByText(v.detail)).toBeTruthy();

    // Partial-analysis banner exactly when the backend reports partial analysis.
    expect(Boolean(screen.queryByText('Partial analysis.'))).toBe(isPartial(result));

    // Every diagnostic, in order, with its severity, code (or rule id) and
    // every recommendation linked to it, with its patch or preview.
    if (result.diagnostics.length === 0) {
      fireEvent.click(screen.getByRole('tab', { name: /Issues/ }));
      expect(screen.getByText('No issues found.')).toBeTruthy();
    } else {
      const rows = within(screen.getByRole('list', { name: 'Issues' })).getAllByRole('listitem');
      expect(rows).toHaveLength(result.diagnostics.length);
      result.diagnostics.forEach((d, i) => {
        const [rule, text] = splitRule(d.message);
        const row = within(rows[i]);
        expect(row.getByText(text)).toBeTruthy();
        expect(row.getByText(SEVERITY_LABEL[d.severity])).toBeTruthy();
        expect(row.getByText(rule ?? d.code)).toBeTruthy();
        const fixes = result.recommendations.filter(r => r.diagnostic_index === i);
        fixes.forEach(r => {
          expect(rows[i].textContent).toContain(`Fix: ${r.title}`);
          if (r.proposed_change?.patch) {
            const patches = row.getAllByLabelText('Patch').map(el => el.textContent);
            expect(patches).toContain(
              r.proposed_change.patch
                .split('\n')
                .map(line => line || '\u00a0')
                .join(''),
            );
          } else if (r.proposed_change?.preview) {
            const previews = row.getAllByLabelText('Preview').map(el => el.textContent);
            expect(previews).toContain(r.proposed_change.preview);
          }
        });
      });
      // Every recommendation is shown under some issue.
      const shown = result.recommendations.filter(r => r.diagnostic_index < result.diagnostics.length);
      expect(shown).toHaveLength(result.recommendations.length);
    }

    // Graph tab: execution order, or the reason it is missing, and an empty
    // graph is explained instead of shown blank.
    fireEvent.click(screen.getByRole('tab', { name: /Graph/ }));
    if (result.execution_order) {
      result.execution_order.forEach((id, i) => {
        expect(screen.getByText(`${i + 1}. ${labelFor(result, id)}`)).toBeTruthy();
      });
    } else {
      expect(screen.getByText(executionOrderNote(result)!)).toBeTruthy();
    }
    expect(Boolean(screen.queryByText('Nothing to draw'))).toBe(result.graph.nodes.length === 0);
  });
});
