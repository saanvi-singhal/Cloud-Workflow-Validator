import { describe, expect, it } from 'vitest';
import {
  cycleHighlights,
  edgeKey,
  executionOrderNote,
  formatLocation,
  getStatus,
  isPartial,
  labelFor,
  nodeSeverities,
  selectionRange,
} from './analysis';
import type { AnalysisResult, SourceLocation } from './types';
import terraformMock from './mocks/terraform.json';
import terraformCycleMock from './mocks/terraform-cycle.json';
import terraformPartialMock from './mocks/terraform-partial.json';
import dockerfileMock from './mocks/dockerfile.json';
import yamlMock from './mocks/yaml.json';
import terraformSample from './samples/main.tf?raw';

// The mocks are real backend output (frontend/scripts/generate_mocks.py).
const terraform = terraformMock as AnalysisResult;
const cycle = terraformCycleMock as AnalysisResult;
const partial = terraformPartialMock as AnalysisResult;
const dockerfile = dockerfileMock as AnalysisResult;
const yaml = yamlMock as AnalysisResult;

const loc = (over: Partial<SourceLocation>): SourceLocation => ({
  file: null,
  start_line: null,
  start_column: null,
  end_line: null,
  end_column: null,
  ...over,
});

describe('getStatus', () => {
  it('follows the backend valid flag', () => {
    expect(getStatus(terraform)).toEqual({ label: 'Invalid', tone: 'error' });
    expect(getStatus(yaml)).toEqual({ label: 'Valid', tone: 'valid' });
    expect(getStatus(dockerfile)).toEqual({ label: 'Valid with warnings', tone: 'warning' });
  });

  it('treats info-only diagnostics as valid', () => {
    const infoOnly: AnalysisResult = {
      ...yaml,
      diagnostics: [
        { code: 'DISCONNECTED_COMPONENT', severity: 'info', message: 'm', source_location: null },
      ],
    };
    expect(getStatus(infoOnly).tone).toBe('valid');
  });
});

describe('partial analysis and execution order', () => {
  it('detects warning-level unsupported constructs only', () => {
    expect(isPartial(partial)).toBe(true);
    expect(isPartial(terraform)).toBe(false);
    expect(isPartial(yaml)).toBe(false);
  });

  it('explains why execution_order is null', () => {
    expect(executionOrderNote(yaml)).toBeNull();
    expect(executionOrderNote(dockerfile)).toMatch(/Not applicable/);
    expect(executionOrderNote(terraform)).toMatch(/errors are fixed/);
    expect(executionOrderNote(partial)).toMatch(/partial/);
  });

  it('shows labels for execution-order node ids', () => {
    expect(yaml.execution_order?.map(id => labelFor(yaml, id))).toEqual([
      'build',
      'test',
      'deploy',
    ]);
    expect(labelFor(yaml, 'missing')).toBe('missing');
  });
});

describe('graph highlighting comes from the backend response', () => {
  it('marks cycle nodes, cycle edges and self-loops from DEPENDENCY_CYCLE recommendations', () => {
    const { nodes, edges, selfLoops } = cycleHighlights(cycle);
    expect([...nodes].sort()).toEqual([
      'tf:resource:aws_s3_bucket.logs',
      'tf:resource:aws_security_group.app',
      'tf:resource:aws_security_group.db',
    ]);
    expect(selfLoops).toEqual(new Set(['tf:resource:aws_s3_bucket.logs']));
    const sgEdges = cycle.graph.edges.filter(e => e.source !== e.target).map(edgeKey);
    expect([...edges].sort()).toEqual(sgEdges.sort());
  });

  it('has no cycle highlights without cycle diagnostics', () => {
    expect(cycleHighlights(terraform).nodes.size).toBe(0);
  });

  it('colours nodes by the most severe linked diagnostic', () => {
    expect(nodeSeverities(terraform).get('tf:resource:aws_subnet.app')).toBe('error');
    expect(nodeSeverities(dockerfile).get('docker:stage:1')).toBe('warning');
    expect(nodeSeverities(yaml).size).toBe(0);
  });
});

describe('source locations', () => {
  it('formats locations and tolerates nulls', () => {
    expect(formatLocation(null)).toBeNull();
    expect(formatLocation(loc({}))).toBeNull();
    expect(formatLocation(loc({ start_line: 5 }))).toBe('line 5');
    expect(formatLocation(loc({ start_line: 5, start_column: 21 }))).toBe('line 5, column 21');
  });

  it('selects exactly the span, treating end_column as exclusive', () => {
    const text = 'abc\n  vpc = aws_vpc.mian.id\n';
    const range = selectionRange(
      text,
      loc({ start_line: 2, start_column: 9, end_line: 2, end_column: 24 }),
    );
    expect(range).not.toBeNull();
    expect(text.slice(range!.start, range!.end)).toBe('aws_vpc.mian.id');
  });

  it('falls back to the whole line when columns or the end are missing', () => {
    const text = 'first\nsecond line\nthird';
    const range = selectionRange(text, loc({ start_line: 2 }));
    expect(text.slice(range!.start, range!.end)).toBe('second line');
  });

  it('returns null when there is nothing to select', () => {
    expect(selectionRange('x', null)).toBeNull();
    expect(selectionRange('x', loc({}))).toBeNull();
    expect(selectionRange('x', loc({ start_line: 9 }))).toBeNull();
  });

  it('matches the real backend span for the terraform sample', () => {
    // The mock was generated from this exact sample file.
    const range = selectionRange(terraformSample, terraform.diagnostics[0].source_location);
    expect(terraformSample.slice(range!.start, range!.end)).toBe('aws_vpc.mian.id');
  });
});
