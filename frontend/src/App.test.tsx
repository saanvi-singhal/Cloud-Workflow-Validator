// @vitest-environment jsdom
// UI tests (spec 9.1): format selection and submission, diagnostic display,
// graph integration and API error states. fetch is stubbed with real backend
// output (the mocks are generated from the backend, see scripts/generate_mocks.py).
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
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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

describe('submitting a configuration', () => {
  it('sends the chosen format and source, then shows status, diagnostics and fixes', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(ok(terraformMock));
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/validate$/);
    const body = JSON.parse(String(init.body));
    expect(body.format).toBe('terraform');
    expect(body.source).toContain('aws_vpc.mian');

    expect(await screen.findByText('Invalid')).toBeTruthy();
    expect(screen.getByText(/ERROR · UNRESOLVED_DEPENDENCY/)).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Suggested fixes' })).toBeTruthy();
  });

  it('sends the format picked in the selector', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(ok(dockerfileMock));
    render(<App />);

    await user.selectOptions(screen.getByLabelText('Input format'), 'dockerfile');
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.parse(String(init.body)).format).toBe('dockerfile');
    expect(await screen.findByText('Valid with warnings')).toBeTruthy();
  });

  it('asks for input instead of calling the API when the editor is empty', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(ok(terraformMock));
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/Please paste some code/)).toBeTruthy();
  });

  it('clears current input when the clear input button is clicked', async () => {
    const user = userEvent.setup();
    render(<App />);

    const clearBtn = screen.getByRole('button', { name: 'Clear input' }) as HTMLButtonElement;
    expect(clearBtn.disabled).toBe(true);

    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    expect(clearBtn.disabled).toBe(false);

    const textarea = screen.getByPlaceholderText(/Paste your terraform code here/) as HTMLTextAreaElement;
    expect(textarea.value).not.toBe('');

    await user.click(clearBtn);
    expect(textarea.value).toBe('');
    expect(clearBtn.disabled).toBe(true);
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
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    expect(await screen.findByText("Couldn't analyze")).toBeTruthy();
    expect(screen.getByText(message)).toBeTruthy();
  });
});

describe('graph integration', () => {
  it('clicking a diagnostic opens the details of its node', async () => {
    const user = userEvent.setup();
    stubFetch(ok(terraformMock));
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await user.click(await screen.findByText(/ERROR · UNRESOLVED_DEPENDENCY/));

    const details = screen.getByRole('button', { name: 'Close node details' }).closest('section')!;
    expect(within(details).getByText('tf:resource:aws_subnet.app')).toBeTruthy();
    expect(within(details).getByText('Issues')).toBeTruthy();
  });

  it('lists a Dockerfile stage’s instructions in its details', async () => {
    const user = userEvent.setup();
    stubFetch(ok(dockerfileMock));
    render(<App />);

    await user.selectOptions(screen.getByLabelText('Input format'), 'dockerfile');
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    // The unreachable-stage warning is linked to the `test` stage.
    await user.click(await screen.findByText(/WARNING · UNREACHABLE_NODE/));

    const details = screen.getByRole('button', { name: 'Close node details' }).closest('section')!;
    expect(within(details).getByText('Instructions')).toBeTruthy();
    expect(within(details).getByText('RUN npm test')).toBeTruthy();
  });
});


describe('multifile upload and analysis', () => {
  it('loads multi-file sample and submits files list payload', async () => {
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
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/validate$/);
    const body = JSON.parse(String(init.body));
    expect(body.files).toHaveLength(3);
    expect(body.files[0].filename).toBe('variables.tf');

    expect(await screen.findByText('Validated 3 files')).toBeTruthy();
    expect(screen.getByText('Variables & Occurrences Across Files')).toBeTruthy();
    expect(screen.getAllByText('var.vpc_cidr').length).toBeGreaterThan(0);
    expect(screen.getByText('Cross-file Reference')).toBeTruthy();
  });
});

describe('mixed formats', () => {
  it('loads the mixed sample and sends every file with format "mixed"', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(ok(mixedMock));
    render(<App />);

    await user.selectOptions(screen.getByLabelText('Input format'), 'mixed');
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze 4 files' }));

    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    const body = JSON.parse(String(init.body));
    expect(body.format).toBe('mixed');
    expect(body.files.map((f: { filename: string }) => f.filename)).toEqual([
      'ci.yml',
      'Dockerfile',
      'install-tools.sh',
      'scan.sh',
    ]);
    expect(await screen.findByText(/GHA_UNPINNED_ACTION/)).toBeTruthy();
    expect(screen.getByText(/Not shown for mixed formats/)).toBeTruthy();
  });

  it('a new file is named right away, and a second format switches to mixed', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.selectOptions(screen.getByLabelText('Input format'), 'dockerfile');
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: '+ Add file' }));
    const input = screen.getByLabelText('File name');
    await user.clear(input);
    await user.type(input, 'build.sh{Enter}');
    expect(screen.getByText('build.sh')).toBeTruthy();
    // A script next to a Dockerfile is build context: still Dockerfile mode.
    expect((screen.getByLabelText('Input format') as HTMLSelectElement).value).toBe(
      'dockerfile',
    );

    await user.dblClick(screen.getByText('file_1'));
    const rename = screen.getByLabelText('File name');
    await user.type(rename, 'Dockerfile{Enter}');
    await user.click(screen.getByRole('button', { name: '+ Add file' }));
    const third = screen.getByLabelText('File name');
    await user.clear(third);
    await user.type(third, 'ci.yml{Enter}');
    expect((screen.getByLabelText('Input format') as HTMLSelectElement).value).toBe('mixed');
  });
});

describe('graph diff', () => {
  it('compares two versions and colours what changed', async () => {
    const user = userEvent.setup();
    const oldGraph = {
      ...terraformMock,
      diagnostics: [],
      recommendations: [],
      graph: {
        nodes: terraformMock.graph.nodes.slice(0, 1),
        edges: [],
      },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(ok(oldGraph))
      .mockResolvedValueOnce(ok(terraformMock));
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Compare versions' }));
    fireEvent.change(screen.getByPlaceholderText('Paste the old configuration here'), {
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
  it('shows a patch with copy and download instead of the preview', async () => {
    const user = userEvent.setup();
    stubFetch(ok(terraformMock));
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    const patch = await screen.findByLabelText('Patch');
    expect(patch.textContent).toContain('--- a/main.tf');
    expect(patch.textContent).toContain('-  tags   = { vpc = aws_vpc.mian.id }');
    expect(patch.textContent).toContain('+  tags   = { vpc = aws_vpc.main.id }');
    expect(screen.getByRole('button', { name: 'Copy patch' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download .patch' })).toBeTruthy();
  });
});

describe('layer and cache advisor', () => {
  it('groups Dockerfile size and cache findings', async () => {
    const user = userEvent.setup();
    const message = (rule: string) => `[${rule}] advice`;
    const advised = {
      ...dockerfileMock,
      diagnostics: [
        ...dockerfileMock.diagnostics,
        ...['DF_APT_NO_RECOMMENDS', 'DF_PIP_NO_CACHE_DIR', 'DF_MULTI_STAGE_OPPORTUNITY'].map(
          (rule, i) => ({
            code: 'SECURITY_RULE_VIOLATION',
            severity: 'info',
            message: message(rule),
            source_location: { file: null, start_line: 10 + i, start_column: 1, end_line: null, end_column: null },
          }),
        ),
      ],
    };
    stubFetch(ok(advised));
    render(<App />);

    await user.selectOptions(screen.getByLabelText('Input format'), 'dockerfile');
    await user.click(screen.getByRole('button', { name: 'Load sample' }));
    await user.click(screen.getByRole('button', { name: 'Analyze' }));

    const panel = await screen.findByLabelText('Layer and cache advisor');
    expect(within(panel).getByText('Image size')).toBeTruthy();
    expect(within(panel).getByText('Multi-stage')).toBeTruthy();
    expect(within(panel).queryByText('Cache order')).toBeNull();
    expect(within(panel).getByText('DF_PIP_NO_CACHE_DIR · line 11')).toBeTruthy();
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
    await user.click(screen.getByRole('button', { name: 'Analyze' }));
    await user.click(await screen.findByText(/ERROR · UNRESOLVED_DEPENDENCY/));

    const panel = screen.getByLabelText('Blast radius');
    expect(panel.textContent).toMatch(/Nothing in this graph depends on \S*app, so changing/);
    expect(within(panel).queryByRole('button', { name: 'Show on graph' })).toBeNull();
  });
});
