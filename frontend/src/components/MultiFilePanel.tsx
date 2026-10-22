import type { MultiFileSummary, SourceLocation, VariableOccurrence } from '../types';

interface Props {
  summary: MultiFileSummary;
  onJumpToFile: (filename: string, location?: SourceLocation | null) => void;
}

const FORMAT_LABEL: Record<string, string> = {
  yaml: 'GitHub Actions workflow',
  dockerfile: 'Dockerfile',
  terraform: 'Terraform',
  build_context: 'Build context (used by a Dockerfile)',
  unknown: 'Not analysed',
};

// What a dependency between two files means, in the user's terms.
const LINK_LABEL: Record<string, string> = {
  terraform_reference: 'is referenced by',
  terraform_explicit_dependency: 'is listed in depends_on by',
  workflow_dependency: 'is needed by',
  docker_stage_base: 'is a stage used by',
  docker_build_context: 'is copied or run by',
};

function variableStatus(v: VariableOccurrence): { text: string; tone: string } {
  if (v.is_duplicate) return { text: 'Declared more than once', tone: 'text-error' };
  if (v.declared_files.length === 0) return { text: 'Undeclared', tone: 'text-error' };
  if (v.is_unused) return { text: 'Unused', tone: 'text-warning' };
  if (v.referenced_files.some(f => !v.declared_files.includes(f))) {
    return { text: 'Cross-file reference', tone: 'text-ok' };
  }
  return { text: 'Used in the same file', tone: 'text-muted' };
}

function FileButton({ name, onClick }: { name: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="font-mono text-sm text-accent hover:underline">
      {name}
    </button>
  );
}

/** The files analysed together, what links them, and shared Terraform variables. */
export default function MultiFilePanel({ summary, onJumpToFile }: Props) {
  const formats = summary.file_formats ?? {};
  const links = summary.interfile_dependencies;
  const variables = summary.variable_occurrences;

  return (
    <div className="space-y-6">
      <section aria-label="Files">
        <h3 className="font-semibold text-ink">Files</h3>
        <ul className="mt-2 divide-y divide-line-soft rounded-md border border-line-soft">
          {summary.files.map(f => (
            <li key={f} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
              <FileButton name={f} onClick={() => onJumpToFile(f)} />
              {formats[f] && (
                <span className="text-sm text-muted">{FORMAT_LABEL[formats[f]] ?? formats[f]}</span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Dependencies between files">
        <h3 className="font-semibold text-ink">Dependencies between files</h3>
        {links.length === 0 ? (
          <p className="mt-1 text-sm text-muted">No file depends on another one.</p>
        ) : (
          <ul className="mt-2 divide-y divide-line-soft rounded-md border border-line-soft">
            {links.map((dep, i) => (
              <li key={`${dep.source_node}-${dep.target_node}-${i}`} className="px-3 py-2 text-sm text-muted">
                {(dep.symbol ?? dep.source_node) === dep.source_file ? (
                  <FileButton name={dep.source_file} onClick={() => onJumpToFile(dep.source_file)} />
                ) : (
                  <>
                    <span className="font-mono text-ink">{dep.symbol ?? dep.source_node}</span> in{' '}
                    <FileButton name={dep.source_file} onClick={() => onJumpToFile(dep.source_file)} />
                  </>
                )}{' '}
                {LINK_LABEL[dep.edge_type] ?? 'is used by'}{' '}
                <FileButton name={dep.target_file} onClick={() => onJumpToFile(dep.target_file)} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {variables.length > 0 && (
        <section aria-label="Variables">
          <h3 className="font-semibold text-ink">Variables</h3>
          <p className="text-sm text-muted">
            Where each Terraform variable is declared and used, across all files.
          </p>
          <div className="mt-2 overflow-x-auto rounded-md border border-line-soft">
            <table className="w-full text-left text-sm">
              <thead className="bg-paper text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Variable</th>
                  <th className="px-3 py-2 font-medium">Declared in</th>
                  <th className="px-3 py-2 font-medium">Used in</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-soft">
                {variables.map(v => {
                  const status = variableStatus(v);
                  return (
                    <tr key={v.name}>
                      <td className="px-3 py-2 font-mono text-ink">var.{v.name}</td>
                      <td className="px-3 py-2">
                        {v.declared_files.length ? (
                          v.declared_files.map(f => (
                            <span key={f} className="mr-2">
                              <FileButton name={f} onClick={() => onJumpToFile(f, v.locations[0] ?? null)} />
                            </span>
                          ))
                        ) : (
                          <span className="text-faint">Nowhere</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {v.referenced_files.length ? (
                          v.referenced_files.map(f => (
                            <span key={f} className="mr-2">
                              <FileButton name={f} onClick={() => onJumpToFile(f)} />
                            </span>
                          ))
                        ) : (
                          <span className="text-faint">Nowhere</span>
                        )}
                      </td>
                      <td className={`px-3 py-2 ${status.tone}`}>{status.text}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
