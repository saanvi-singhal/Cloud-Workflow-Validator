import type { MultiFileSummary, SourceLocation } from '../types';

interface Props {
  summary: MultiFileSummary;
  onJumpToFile: (filename: string, location?: SourceLocation | null) => void;
}

export default function MultiFilePanel({ summary, onJumpToFile }: Props) {
  const hasDuplicate = summary.duplicate_variables.length > 0;
  const hasUnused = summary.unused_variables.length > 0;

  return (
    <div className="mt-6 space-y-6">
      {/* Top statistics overview */}
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-xs">
          <div className="text-xs font-medium text-slate-500">Files Analyzed</div>
          <div className="mt-1 text-2xl font-bold text-slate-800">{summary.files.length}</div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {summary.files.map(f => (
              <button
                key={f}
                onClick={() => onJumpToFile(f)}
                className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-mono text-slate-700 hover:border-sky-300 hover:bg-sky-50 hover:text-sky-700 transition-colors"
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-xs">
          <div className="text-xs font-medium text-slate-500">Inter-file Dependencies</div>
          <div className="mt-1 text-2xl font-bold text-sky-600">
            {summary.interfile_dependencies.length}
          </div>
          <div className="mt-1 text-xs text-slate-500">Cross-boundary references</div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-xs">
          <div className="text-xs font-medium text-slate-500">Variables Tracked</div>
          <div className="mt-1 text-2xl font-bold text-slate-800">
            {summary.variable_occurrences.length}
          </div>
          <div className="mt-1 text-xs text-slate-500">Across all uploaded files</div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-xs">
          <div className="text-xs font-medium text-slate-500">Issues & Status</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span
              className={`text-2xl font-bold ${hasDuplicate ? 'text-red-600' : 'text-emerald-600'}`}
            >
              {hasDuplicate ? summary.duplicate_variables.length : 0}
            </span>
            <span className="text-xs text-slate-500">duplicates</span>
          </div>
          {hasUnused && (
            <div className="mt-1 text-xs font-medium text-amber-600">
              {summary.unused_variables.length} unused variable(s)
            </div>
          )}
        </div>
      </div>

      {/* Variable Occurrences Across Files */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
        <h3 className="flex items-center gap-2 text-base font-semibold text-slate-900">
          <span>Variables & Occurrences Across Files</span>
          <span className="rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700 border border-sky-100">
            {summary.variable_occurrences.length}
          </span>
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          Detects shared variable references, duplicate declarations across files, and unused variables.
        </p>

        {summary.variable_occurrences.length === 0 ? (
          <p className="mt-3 text-xs text-slate-400 italic">No variables declared or referenced.</p>
        ) : (
          <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-slate-600">
                  <th className="py-2.5 px-3 font-semibold">Variable Name</th>
                  <th className="py-2.5 px-3 font-semibold">Declared In</th>
                  <th className="py-2.5 px-3 font-semibold">Referenced In</th>
                  <th className="py-2.5 px-3 font-semibold">Occurrences</th>
                  <th className="py-2.5 px-3 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-sans">
                {summary.variable_occurrences.map(v => {
                  const isShared = v.declared_files.length > 0 && v.referenced_files.length > 0;
                  return (
                    <tr key={v.name} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-2.5 px-3 font-mono font-medium text-slate-800">
                        var.{v.name}
                      </td>
                      <td className="py-2.5 px-3">
                        {v.declared_files.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {v.declared_files.map(f => (
                              <button
                                key={f}
                                onClick={() => onJumpToFile(f, v.locations[0] ?? null)}
                                className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-700 hover:border-sky-300 hover:bg-sky-50 hover:text-sky-700 transition-colors"
                              >
                                {f}
                              </button>
                            ))}
                          </div>
                        ) : (
                          <span className="font-medium text-red-600">Undeclared</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3">
                        {v.referenced_files.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {v.referenced_files.map(f => (
                              <button
                                key={f}
                                onClick={() => onJumpToFile(f)}
                                className="rounded border border-sky-100 bg-sky-50 px-1.5 py-0.5 font-mono text-[11px] text-sky-700 hover:bg-sky-100 transition-colors"
                              >
                                {f}
                              </button>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-400 italic">None</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 font-semibold text-slate-700">
                        {v.total_occurrences}
                      </td>
                      <td className="py-2.5 px-3">
                        {v.is_duplicate ? (
                          <span className="rounded-full bg-red-100 px-2.5 py-0.5 font-medium text-red-700">
                            Duplicate Declaration
                          </span>
                        ) : v.is_unused ? (
                          <span className="rounded-full bg-amber-100 px-2.5 py-0.5 font-medium text-amber-700">
                            Unused Variable
                          </span>
                        ) : isShared ? (
                          <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 font-medium text-emerald-700">
                            Cross-file Reference
                          </span>
                        ) : (
                          <span className="rounded-full bg-slate-100 px-2.5 py-0.5 font-medium text-slate-600">
                            Local
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Inter-File Dependencies */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs">
        <h3 className="flex items-center gap-2 text-base font-semibold text-slate-900">
          <span>Inter-File Dependencies</span>
          <span className="rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700 border border-sky-100">
            {summary.interfile_dependencies.length}
          </span>
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          Cross-file edges showing prerequisites and data dependencies between different files.
        </p>

        {summary.interfile_dependencies.length === 0 ? (
          <p className="mt-3 text-xs text-slate-400 italic">
            No dependencies crossing file boundaries found.
          </p>
        ) : (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {summary.interfile_dependencies.map((dep, idx) => (
              <div
                key={`${dep.source_node}-${dep.target_node}-${idx}`}
                className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50/70 p-2.5 text-xs"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 font-mono">
                    <button
                      onClick={() => onJumpToFile(dep.source_file)}
                      className="font-medium text-sky-700 hover:text-sky-800 hover:underline"
                    >
                      {dep.source_file}
                    </button>
                    <svg className="h-3 w-3 shrink-0 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                    <button
                      onClick={() => onJumpToFile(dep.target_file)}
                      className="font-medium text-sky-700 hover:text-sky-800 hover:underline"
                    >
                      {dep.target_file}
                    </button>
                  </div>
                  <div className="mt-1 truncate font-mono text-[11px] text-slate-500">
                    Symbol: <span className="font-medium text-slate-800">{dep.symbol ?? dep.source_node}</span>
                  </div>
                </div>
                <span className="ml-2 rounded bg-sky-50 border border-sky-100 px-1.5 py-0.5 text-[10px] uppercase font-semibold text-sky-700">
                  {dep.edge_type.replace('terraform_', '')}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
