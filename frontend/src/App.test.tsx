// @vitest-environment jsdom
// UI tests (spec 9.1): navigation, format selection and submission, the
// verdict, issues with their fixes, graph integration and API error states.
// fetch is stubbed with real backend output (the mocks are generated from the
// backend, see scripts/generate_mocks.py).
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import terraformMock from './mocks/terraform.json';
import dockerfileMock from './mocks/dockerfile.json';
import mixedMock from './mocks/mixed.json';
import yamlMock from './mocks/yaml.json';
import NodeDetails from './components/NodeDetails';
import { blastRadius } from './blastRadius';
import type { AnalysisResult } from './types';

beforeAll(() => {
  // React Flow measures its container; jsdom has no layout engine.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  // jsdom has no scrolling; the router scrolls to the top on page change.
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = '';
});

function stubFetch(response: Partial<Response> | Error) {
  const fetchMock = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const ok = (body: unknown): Partial<Response> => ({
  ok: true,
  status: 200,
  json: async () => body,
});

const analyzeButton = () => screen.getByRole('button', { name: 'Analyze' });
const formatRadio = (name: string) =>
  within(screen.getByRole('radiogroup', { name: 'Input format' })).getByRole('radio', { name });

/** The issue row whose text matches, as a scope for queries. */
function issue(text: RegExp | string) {
  const list = screen.getByRole('list', { name: 'Issues' });
  const row = within(list)
    .getAllByRole('listitem')
    .find(li => (typeof text === 'string' ? li.textContent?.includes(text) : text.test(li.textContent ?? '')));
  if (!row) throw new Error(`no issue matching ${text}`);
  return within(row);
}

describe('navigation', () => {
  it('switches pages from the top bar and marks the current one', async () => {
    const user = userEvent.setup();
    render(<App />);
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Analyze' }).getAttribute('aria-current')).toBe('page');

    await user.click(within(nav).getByRole('link', { name: 'How it works' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'How it works' })).toBeTruthy();
    expect(within(nav).getByRole('link', { name: 'How it works' }).getAttribute('aria-current')).toBe('page');

    await user.click(within(nav).getByRole('link', { name: 'Compare versions' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Compare versions' })).toBeTruthy();
  });

  it('keeps the input and result when you leave the Analyze page and come back', async () => {
    const user = userEvent.setup();
    stubFetch(ok(terraformMock));
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(analyzeButton());
    await screen.findByText('Not ready to deploy');

    const nav = screen.getByRole('navigation', { name: 'Main' });
    await user.click(within(nav).getByRole('link', { name: 'How it works' }));
    await user.click(within(nav).getByRole('link', { name: 'Analyze' }));
    expect(await screen.findByText('Not ready to deploy')).toBeTruthy();
  });
});

describe('submitting a configuration', () => {
  it('sends the chosen format and source, then shows the verdict and issues with fixes', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(ok(terraformMock));
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(analyzeButton());

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/validate$/);
    const body = JSON.parse(String(init.body));
    expect(body.format).toBe('terraform');
    expect(body.source).toContain('aws_vpc.mian');

    expect(await screen.findByRole('heading', { name: 'Not ready to deploy' })).toBeTruthy();
    expect(screen.getByText('1 error to fix.')).toBeTruthy();
    const row = issue('UNRESOLVED_DEPENDENCY');
    expect(row.getByText('Error')).toBeTruthy();
    expect(row.getByText(/Fix: Did you mean 'aws_vpc.main'\?/)).toBeTruthy();
  });

  it('sends the format picked in the format switch', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(ok(dockerfileMock));
    render(<App />);

    await user.click(formatRadio('Dockerfile'));
    expect(formatRadio('Dockerfile').getAttribute('aria-checked')).toBe('true');
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(analyzeButton());

    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.parse(String(init.body)).format).toBe('dockerfile');
    expect(await screen.findByRole('heading', { name: 'Ready, with warnings to review' })).toBeTruthy();
  });

  it('filters issues by severity', async () => {
    const user = userEvent.setup();
    stubFetch(ok(mixedMock)); // warnings and suggestions
    render(<App />);
    await user.click(formatRadio('Mixed'));
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze 4 files' }));
    await screen.findByRole('list', { name: 'Issues' });

    const all = within(screen.getByRole('list', { name: 'Issues' })).getAllByRole('listitem').length;
    await user.click(screen.getByRole('button', { name: /^Warnings/ }));
    const warnings = within(screen.getByRole('list', { name: 'Issues' })).getAllByRole('listitem');
    expect(warnings.length).toBeLessThan(all);
    expect(warnings.every(li => li.textContent?.startsWith('Warning'))).toBe(true);
  });

  it('asks for input instead of calling the API when the editor is empty', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(ok(terraformMock));
    render(<App />);

    await user.click(analyzeButton());

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/Paste a configuration, upload files or try a sample first/)).toBeTruthy();
  });

  it('Clear returns the page to its first-load state', async () => {
    const user = userEvent.setup();
    stubFetch(ok(mixedMock));
    render(<App />);

    const clearBtn = screen.getByRole('button', { name: 'Clear' }) as HTMLButtonElement;
    expect(clearBtn.disabled).toBe(true);

    // Several files, another format, and a result on screen.
    await user.click(formatRadio('Mixed'));
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze 4 files' }));
    await screen.findByRole('list', { name: 'Issues' });
    expect(clearBtn.disabled).toBe(false);

    await user.click(clearBtn);
    expect(formatRadio('Terraform').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText('untitled')).toBeTruthy();
    expect(screen.queryByText('ci.yml')).toBeNull();
    expect((screen.getByLabelText('Configuration source') as HTMLTextAreaElement).value).toBe('');
    expect(screen.queryByRole('list', { name: 'Issues' })).toBeNull();
    expect(screen.getByRole('heading', { name: "Find out whether it's safe to deploy" })).toBeTruthy();
    expect(clearBtn.disabled).toBe(true);
  });

  it('runs an example straight from the start panel', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(ok(yamlMock));
    render(<App />);

    await user.click(screen.getByRole('button', { name: /A GitHub Actions workflow/ }));

    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.parse(String(init.body)).format).toBe('yaml');
    expect(await screen.findByRole('heading', { name: 'Ready to deploy' })).toBeTruthy();
    // With no issues the graph is shown first.
    expect(screen.getByRole('tab', { name: /Graph/ }).getAttribute('aria-selected')).toBe('true');
  });
});

describe('API error states', () => {
  it.each([
    ['an unreachable server', new TypeError('Failed to fetch'), /Can't reach the server/],
    ['a 413 response', { ok: false, status: 413 }, /too large/],
    ['a 422 response', { ok: false, status: 422 }, /rejected the request \(422\)/],
    ['a 500 response', { ok: false, status: 500 }, /returned an error \(500\)/],
  ] as const)('explains %s', async (_, response, message) => {
    const user = userEvent.setup();
    stubFetch(response as Partial<Response> | Error);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(analyzeButton());

    expect(await screen.findByText("Couldn't analyze")).toBeTruthy();
    expect(screen.getByText(message)).toBeTruthy();
  });
});

describe('graph integration', () => {
  it('"Show in graph" opens the graph with the details of the issue’s node', async () => {
    const user = userEvent.setup();
    stubFetch(ok(terraformMock));
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(analyzeButton());
    await screen.findByRole('list', { name: 'Issues' });
    await user.click(issue('UNRESOLVED_DEPENDENCY').getByRole('button', { name: 'Show in graph' }));

    expect(screen.getByRole('tab', { name: /Graph/ }).getAttribute('aria-selected')).toBe('true');
    const details = screen.getByRole('button', { name: 'Close node details' }).closest('section')!;
    expect(within(details).getByText('tf:resource:aws_subnet.app')).toBeTruthy();
    expect(within(details).getByText('Issues')).toBeTruthy();
  });

  it('lists a Dockerfile stage’s instructions in its details', async () => {
    const user = userEvent.setup();
    stubFetch(ok(dockerfileMock));
    render(<App />);

    await user.click(formatRadio('Dockerfile'));
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(analyzeButton());
    await screen.findByRole('list', { name: 'Issues' });
    // The unreachable-stage warning is linked to the `test` stage.
    await user.click(issue('UNREACHABLE_NODE').getByRole('button', { name: 'Show in graph' }));

    const details = screen.getByRole('button', { name: 'Close node details' }).closest('section')!;
    expect(within(details).getByText('Instructions')).toBeTruthy();
    expect(within(details).getByText('RUN npm test')).toBeTruthy();
  });
});

describe('multifile upload and analysis', () => {
  it('loads the multi-file sample, submits the files and shows them in the Files tab', async () => {
    const user = userEvent.setup();
    const mockMultiResult = {
      valid: true,
      format: 'terraform',
      diagnostics: [],
      graph: {
        nodes: [
          {
            id: 'tf:variable:vpc_cidr',
            label: 'var.vpc_cidr',
            type: 'variable',
            source_location: { file: 'variables.tf', start_line: 1, start_column: 1, end_line: 4, end_column: 2 },
            metadata: { file: 'variables.tf' },
          },
          {
            id: 'tf:resource:aws_vpc.main',
            label: 'aws_vpc.main',
            type: 'resource',
            source_location: { file: 'main.tf', start_line: 1, start_column: 1, end_line: 3, end_column: 2 },
            metadata: { file: 'main.tf' },
          },
        ],
        edges: [
          {
            source: 'tf:variable:vpc_cidr',
            target: 'tf:resource:aws_vpc.main',
            type: 'terraform_reference',
            label: 'cidr_block',
            source_location: null,
            metadata: { is_interfile: true, source_file: 'variables.tf', target_file: 'main.tf' },
          },
        ],
      },
      execution_order: ['tf:variable:vpc_cidr', 'tf:resource:aws_vpc.main'],
      recommendations: [],
      multifile: {
        files: ['variables.tf', 'main.tf', 'outputs.tf'],
        interfile_dependencies: [
          {
            source_node: 'tf:variable:vpc_cidr',
            target_node: 'tf:resource:aws_vpc.main',
            source_file: 'variables.tf',
            target_file: 'main.tf',
            edge_type: 'terraform_reference',
            symbol: 'var.vpc_cidr',
          },
        ],
        variable_occurrences: [
          {
            name: 'vpc_cidr',
            declared_files: ['variables.tf'],
            referenced_files: ['main.tf'],
            total_occurrences: 2,
            is_duplicate: false,
            is_unused: false,
            locations: [],
          },
        ],
        duplicate_variables: [],
        unused_variables: [],
      },
    };

    const fetchMock = stubFetch(ok(mockMultiResult));
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Load multi-file sample' }));
    expect(screen.getByText('variables.tf')).toBeTruthy();
    expect(screen.getByText('main.tf')).toBeTruthy();
    expect(screen.getByText('outputs.tf')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Analyze 3 files' }));

    expect(fetchMock).toHaveBeenCalledOnce();
    const body = JSON.parse(String((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body));
    expect(body.files).toHaveLength(3);
    expect(body.files[0].filename).toBe('variables.tf');

    expect(await screen.findByText('Checked 3 files together.')).toBeTruthy();
    await user.click(screen.getByRole('tab', { name: /Files/ }));
    const variables = screen.getByRole('region', { name: 'Variables' });
    expect(within(variables).getByText('var.vpc_cidr')).toBeTruthy();
    expect(within(variables).getByText('Cross-file reference')).toBeTruthy();
    const links = screen.getByRole('region', { name: 'Dependencies between files' });
    expect(links.textContent).toContain('var.vpc_cidr in variables.tf is referenced by main.tf');
  });
});

describe('mixed formats', () => {
  it('loads the mixed sample and sends every file with format "mixed"', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(ok(mixedMock));
    render(<App />);

    await user.click(formatRadio('Mixed'));
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze 4 files' }));

    const body = JSON.parse(String((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body));
    expect(body.format).toBe('mixed');
    expect(body.files.map((f: { filename: string }) => f.filename)).toEqual([
      'ci.yml',
      'Dockerfile',
      'install-tools.sh',
      'scan.sh',
    ]);
    expect(await screen.findByText('GHA_UNPINNED_ACTION')).toBeTruthy();
    await user.click(screen.getByRole('tab', { name: /Graph/ }));
    expect(screen.getByText(/Not shown for mixed formats/)).toBeTruthy();
  });

  it('a new file is named right away, and a second format switches to mixed', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(formatRadio('Dockerfile'));
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: '+ Add file' }));
    const input = screen.getByLabelText('File name');
    await user.clear(input);
    await user.type(input, 'build.sh{Enter}');
    expect(screen.getByText('build.sh')).toBeTruthy();
    // A script next to a Dockerfile is build context: still Dockerfile mode.
    expect(formatRadio('Dockerfile').getAttribute('aria-checked')).toBe('true');

    await user.dblClick(screen.getByText('file_1'));
    await user.type(screen.getByLabelText('File name'), 'Dockerfile{Enter}');
    await user.click(screen.getByRole('button', { name: '+ Add file' }));
    const third = screen.getByLabelText('File name');
    await user.clear(third);
    await user.type(third, 'ci.yml{Enter}');
    expect(formatRadio('Mixed').getAttribute('aria-checked')).toBe('true');
  });
});

describe('graph diff', () => {
  it('compares two versions and colours what changed', async () => {
    const user = userEvent.setup();
    const oldGraph = {
      ...terraformMock,
      diagnostics: [],
      recommendations: [],
      graph: { nodes: terraformMock.graph.nodes.slice(0, 1), edges: [] },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(ok(oldGraph))
      .mockResolvedValueOnce(ok(terraformMock));
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    await user.click(screen.getByRole('link', { name: 'Compare versions' }));
    fireEvent.change(await screen.findByPlaceholderText('Paste the old configuration here'), {
      target: { value: 'resource "a" "b" {}' },
    });
    fireEvent.change(screen.getByPlaceholderText('Paste the new configuration here'), {
      target: { value: 'resource "a" "b" {}\nresource "c" "d" {}' },
    });
    await user.click(screen.getByRole('button', { name: 'Compare graphs' }));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const added = terraformMock.graph.nodes.length - 1;
    expect(await screen.findByText(`${added} added nodes`)).toBeTruthy();
    expect(screen.getByText('Old version graph')).toBeTruthy();
    expect(screen.getByText('New version graph')).toBeTruthy();
  });
});

describe('fix patches', () => {
  it('shows the patch, with copy and download, inside the issue’s fix', async () => {
    const user = userEvent.setup();
    stubFetch(ok(terraformMock));
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(analyzeButton());
    await screen.findByRole('list', { name: 'Issues' });

    const row = issue('UNRESOLVED_DEPENDENCY');
    const patch = row.getByLabelText('Patch');
    expect(patch.textContent).toContain('--- a/main.tf');
    expect(patch.textContent).toContain('-  tags   = { vpc = aws_vpc.mian.id }');
    expect(patch.textContent).toContain('+  tags   = { vpc = aws_vpc.main.id }');
    expect(row.getByRole('button', { name: 'Copy patch' })).toBeTruthy();
    expect(row.getByRole('button', { name: 'Download .patch' })).toBeTruthy();
  });
});

describe('layer and cache advisor', () => {
  it('groups Dockerfile size and cache findings in the Build advisor tab', async () => {
    const user = userEvent.setup();
    const advised = {
      ...dockerfileMock,
      diagnostics: [
        ...dockerfileMock.diagnostics,
        ...['DF_APT_NO_RECOMMENDS', 'DF_PIP_NO_CACHE_DIR', 'DF_MULTI_STAGE_OPPORTUNITY'].map(
          (rule, i) => ({
            code: 'SECURITY_RULE_VIOLATION',
            severity: 'info',
            message: `[${rule}] advice ${i}`,
            source_location: { file: null, start_line: 10 + i, start_column: 1, end_line: null, end_column: null },
          }),
        ),
      ],
    };
    stubFetch(ok(advised));
    render(<App />);

    await user.click(formatRadio('Dockerfile'));
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(analyzeButton());
    await user.click(await screen.findByRole('tab', { name: /Build advisor/ }));

    const panel = screen.getByLabelText('Layer and cache advisor');
    expect(within(panel).getByText('Image size')).toBeTruthy();
    expect(within(panel).getByText('Multi-stage builds')).toBeTruthy();
    expect(within(panel).queryByText('Cache order')).toBeNull();
    expect(within(panel).getByText('advice 1').parentElement?.textContent).toContain('line 11');
  });
});

describe('blast radius', () => {
  it('lists what depends on a node, by distance, and toggles the graph view', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const onSelect = vi.fn();
    const result = yamlMock as AnalysisResult;
    const build = result.graph.nodes.find(n => n.id === 'gha:job:build')!;
    render(
      <NodeDetails
        result={result}
        node={build}
        onJump={() => {}}
        onSelectDiagnostic={() => {}}
        onClose={() => {}}
        blast={blastRadius(result, build.id)}
        onToggleBlast={onToggle}
        onSelectNode={onSelect}
      />,
    );

    const panel = screen.getByLabelText('Blast radius');
    expect(panel.textContent).toContain('affects 2 items: 1 directly, 1 through other items');
    expect(within(panel).getByText('Directly (1)')).toBeTruthy();
    expect(within(panel).getByText('2 steps away (1)')).toBeTruthy();
    await user.click(within(panel).getByRole('button', { name: 'deploy' }));
    expect(onSelect).toHaveBeenCalledWith('gha:job:deploy');
    await user.click(within(panel).getByRole('button', { name: 'Show on graph' }));
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it('says when nothing depends on the selected node', async () => {
    const user = userEvent.setup();
    stubFetch(ok(terraformMock));
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(analyzeButton());
    await screen.findByRole('list', { name: 'Issues' });
    await user.click(issue('UNRESOLVED_DEPENDENCY').getByRole('button', { name: 'Show in graph' }));

    const panel = screen.getByLabelText('Blast radius');
    expect(panel.textContent).toMatch(/Nothing in this graph depends on \S*app, so changing/);
    expect(within(panel).queryByRole('button', { name: 'Show on graph' })).toBeNull();
  });
});
