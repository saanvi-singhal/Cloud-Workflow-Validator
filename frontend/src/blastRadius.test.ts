import { describe, expect, it } from 'vitest';
import { blastRadius } from './blastRadius';
import type { AnalysisResult, GraphEdge } from './types';

function graph(edges: [string, string][], extra: string[] = []): AnalysisResult {
  const ids = [...new Set([...edges.flat(), ...extra])];
  return {
    valid: true,
    format: 'terraform',
    diagnostics: [],
    execution_order: null,
    recommendations: [],
    graph: {
      nodes: ids.map(id => ({ id, label: id, type: 'resource', source_location: null, metadata: {} })),
      edges: edges.map(
        ([source, target]): GraphEdge => ({
          source,
          target,
          type: 'terraform_reference',
          label: null,
          source_location: null,
          metadata: {},
        }),
      ),
    },
  } as AnalysisResult;
}

describe('blastRadius', () => {
  it('follows edges downstream only, nearest first', () => {
    // vpc -> subnet -> instance, vpc -> sg -> instance; db is upstream of vpc.
    const result = graph([
      ['db', 'vpc'],
      ['vpc', 'subnet'],
      ['vpc', 'sg'],
      ['subnet', 'instance'],
      ['sg', 'instance'],
    ]);
    const blast = blastRadius(result, 'vpc');
    expect(blast.affected.map(a => [a.id, a.depth])).toEqual([
      ['sg', 1],
      ['subnet', 1],
      ['instance', 2],
    ]);
    // Prerequisites are not affected by a change to their dependents.
    expect(blast.depthOf.has('db')).toBe(false);
    expect(blast.depthOf.has('vpc')).toBe(false);
    // instance is reached first through sg (alphabetical, deterministic).
    expect(blast.affected[2].via.source).toBe('sg');
    expect([...blast.edges].sort()).toEqual([
      'sg->instance:terraform_reference',
      'vpc->sg:terraform_reference',
      'vpc->subnet:terraform_reference',
    ]);
  });

  it('terminates on cycles and ignores self-loops', () => {
    const blast = blastRadius(graph([['a', 'b'], ['b', 'a'], ['b', 'b']]), 'a');
    expect(blast.affected.map(a => a.id)).toEqual(['b']);
  });

  it('is empty for a node nothing depends on', () => {
    const blast = blastRadius(graph([['a', 'b']], ['c']), 'b');
    expect(blast.affected).toEqual([]);
    expect(blast.edges.size).toBe(0);
  });
});
