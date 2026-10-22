import { describe, expect, it } from 'vitest';
import { diffEdgeKey, diffResults } from './graphDiff';
import type { AnalysisResult } from './types';

function result(
  nodeIds: string[],
  edges: [string, string][] = [],
  cycleMessages: string[] = [],
): AnalysisResult {
  return {
    valid: cycleMessages.length === 0,
    format: 'terraform',
    diagnostics: cycleMessages.map(message => ({
      code: 'DEPENDENCY_CYCLE',
      severity: 'error' as const,
      message,
      source_location: null,
    })),
    graph: {
      nodes: nodeIds.map(id => ({
        id,
        label: id,
        type: 'resource',
        source_location: null,
        metadata: {},
      })),
      edges: edges.map(([source, target]) => ({
        source,
        target,
        type: 'terraform_reference',
        label: null,
        source_location: null,
        metadata: {},
      })),
    },
    execution_order: null,
    recommendations: [],
  };
}

const key = (source: string, target: string) =>
  diffEdgeKey({ source, target, type: 'terraform_reference' });

describe('diffResults', () => {
  it('reports identical graphs as unchanged', () => {
    const a = result(['vpc', 'app'], [['vpc', 'app']]);
    const diff = diffResults(a, a);
    expect(diff.identical).toBe(true);
    expect(diff.addedNodes).toEqual([]);
    expect(diff.removedNodes).toEqual([]);
    expect(diff.addedEdges).toEqual([]);
    expect(diff.removedEdges).toEqual([]);
    expect(diff.rewiredNodes).toEqual([]);
  });

  it('finds an added node and edge', () => {
    const oldR = result(['vpc']);
    const newR = result(['vpc', 'app'], [['vpc', 'app']]);
    const diff = diffResults(oldR, newR);
    expect(diff.addedNodes).toEqual(['app']);
    expect(diff.addedEdges).toEqual([key('vpc', 'app')]);
    expect(diff.removedNodes).toEqual([]);
    expect(diff.identical).toBe(false);
  });

  it('finds a removed node and edge', () => {
    const oldR = result(['vpc', 'app'], [['vpc', 'app']]);
    const newR = result(['vpc']);
    const diff = diffResults(oldR, newR);
    expect(diff.removedNodes).toEqual(['app']);
    expect(diff.removedEdges).toEqual([key('vpc', 'app')]);
    expect(diff.addedNodes).toEqual([]);
  });

  it('marks a node as rewired when it switches dependency between existing nodes', () => {
    const oldR = result(['main', 'other', 'app'], [['main', 'app']]);
    const newR = result(['main', 'other', 'app'], [['other', 'app']]);
    const diff = diffResults(oldR, newR);
    expect(diff.addedEdges).toEqual([key('other', 'app')]);
    expect(diff.removedEdges).toEqual([key('main', 'app')]);
    expect(diff.rewiredNodes).toEqual(['app']);
    expect(diff.addedNodes).toEqual([]);
    expect(diff.removedNodes).toEqual([]);
  });

  it('does not call a dependency on a brand-new node a rewire', () => {
    const oldR = result(['app']);
    const newR = result(['app', 'db'], [['db', 'app']]);
    const diff = diffResults(oldR, newR);
    expect(diff.addedNodes).toEqual(['db']);
    expect(diff.addedEdges).toEqual([key('db', 'app')]);
    expect(diff.rewiredNodes).toEqual([]);
  });

  it('reports a cycle that only the new version has', () => {
    const oldR = result(['a', 'b'], [['a', 'b']]);
    const newR = result(['a', 'b'], [['a', 'b'], ['b', 'a']], ['Dependency cycle: a -> b -> a.']);
    const diff = diffResults(oldR, newR);
    expect(diff.newCycles).toHaveLength(1);
    expect(diff.newCycles[0].message).toContain('a -> b -> a');
    expect(diff.resolvedCycles).toEqual([]);
  });

  it('does not report a cycle that both versions have as new', () => {
    const msg = 'Dependency cycle: a -> b -> a.';
    const oldR = result(['a', 'b'], [['a', 'b'], ['b', 'a']], [msg]);
    const newR = result(['a', 'b'], [['a', 'b'], ['b', 'a']], [msg]);
    const diff = diffResults(oldR, newR);
    expect(diff.newCycles).toEqual([]);
    expect(diff.resolvedCycles).toEqual([]);
  });

  it('reports a cycle that the new version fixed', () => {
    const oldR = result(['a', 'b'], [['a', 'b'], ['b', 'a']], ['Dependency cycle: a -> b -> a.']);
    const newR = result(['a', 'b'], [['a', 'b']]);
    const diff = diffResults(oldR, newR);
    expect(diff.resolvedCycles).toHaveLength(1);
    expect(diff.newCycles).toEqual([]);
  });
});