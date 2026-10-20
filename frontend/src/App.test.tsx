// @vitest-environment jsdom
// UI tests (spec 9.1): format selection and submission, diagnostic display,
// graph integration and API error states. fetch is stubbed with real backend
// output (the mocks are generated from the backend, see scripts/generate_mocks.py).
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import terraformMock from './mocks/terraform.json';
import dockerfileMock from './mocks/dockerfile.json';

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
