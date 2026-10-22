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
        <div className="rounded-xl border border-sky-500/20 bg-slate-900/85 p-3.5 shadow-lg backdrop-blur-md">
          <div className="text-[10px] font-mono uppercase tracking-widest text-sky-400/80">Files Analyzed</div>
          <div className="mt-1 font-mono text-2xl font-bold text-white">{summary.files.length}</div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {summary.files.map(f => (
              <button
                key={f}
                onClick={() => onJumpToFile(f)}
                className="rounded border border-slate-700 bg-slate-800/80 px-1.5 py-0.5 text-[10px] font-mono text-slate-300 hover:border-cyan-500/50 hover:bg-slate-700 hover:text-cyan-300 transition-colors"
              >
                {f}
                {summary.file_formats?.[f] && (
                  <span className="ml-1 text-slate-400">
                    · {summary.file_formats[f].replace('_', ' ')}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-sky-500/20 bg-slate-900/85 p-3.5 shadow-lg backdrop-blur-md">
          <div className="text-[10px] font-mono uppercase tracking-widest text-sky-400/80">Inter-file Dependencies</div>
          <div className="mt-1 font-mono text-2xl font-bold text-cyan-400">
            {summary.interfile_dependencies.length}
          </div>
          <div className="mt-1 text-[11px] font-mono text-slate-400">Cross-boundary references</div>
        </div>

        <div className="rounded-xl border border-sky-500/20 bg-slate-900/85 p-3.5 shadow-lg backdrop-blur-md">
          <div className="text-[10px] font-mono uppercase tracking-widest text-sky-400/80">Variables Tracked</div>
          <div className="mt-1 font-mono text-2xl font-bold text-white">
            {summary.variable_occurrences.length}
          </div>
          <div className="mt-1 text-[11px] font-mono text-slate-400">Across all uploaded files</div>
        </div>

        <div className="rounded-xl border border-sky-500/20 bg-slate-900/85 p-3.5 shadow-lg backdrop-blur-md">
          <div className="text-[10px] font-mono uppercase tracking-widest text-sky-400/80">Issues & Status</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span
              className={`font-mono text-2xl font-bold ${hasDuplicate ? 'text-rose-400' : 'text-emerald-400'}`}
            >
              {hasDuplicate ? summary.duplicate_variables.length : 0}
            </span>
            <span className="font-mono text-xs text-slate-400">duplicates</span>
          </div>
          {hasUnused && (
            <div className="mt-1 text-xs font-mono text-amber-400">
              {summary.unused_variables.length} unused variable(s)
            </div>
          )}
        </div>
      </div>

      {/* Variable Occurrences Across Files */}
      <div className="rounded-xl border border-sky-500/20 bg-slate-900/85 p-5 shadow-lg backdrop-blur-md">
        <h3 className="flex items-center gap-2 text-base font-semibold text-white">
          <span>Variables & Occurrences Across Files</span>
          <span className="rounded-full border border-cyan-500/30 bg-cyan-950/80 px-2 py-0.5 font-mono text-xs text-cyan-300">
            {summary.variable_occurrences.length}
          </span>
        </h3>
        <p className="mt-1 text-xs text-slate-400">
          Detects shared variable references, duplicate declarations across files, and unused variables.
        </p>

        {summary.variable_occurrences.length === 0 ? (
          <p className="mt-3 text-xs text-slate-500 italic">No variables declared or referenced.</p>
        ) : (
          <div className="mt-4 overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-950/80 text-sky-400 font-mono">
                  <th className="py-2.5 px-3 font-semibold uppercase tracking-wider">Variable Name</th>
                  <th className="py-2.5 px-3 font-semibold uppercase tracking-wider">Declared In</th>
                  <th className="py-2.5 px-3 font-semibold uppercase tracking-wider">Referenced In</th>
                  <th className="py-2.5 px-3 font-semibold uppercase tracking-wider">Occurrences</th>
                  <th className="py-2.5 px-3 font-semibold uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80 bg-slate-900/50 font-sans">
                {summary.variable_occurrences.map(v => {
                  const isShared = v.declared_files.length > 0 && v.referenced_files.length > 0;
                  return (
                    <tr key={v.name} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-2.5 px-3 font-mono font-medium text-sky-300">
                        var.{v.name}
                      </td>
                      <td className="py-2.5 px-3">
                        {v.declared_files.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {v.declared_files.map(f => (
                              <button
                                key={f}
                                onClick={() => onJumpToFile(f, v.locations[0] ?? null)}
                                className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-slate-300 hover:border-cyan-500/50 hover:text-cyan-300 transition-colors"
                              >
                                {f}
                              </button>
                            ))}
                          </div>
                        ) : (
                          <span className="font-mono text-rose-400 font-medium">Undeclared</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3">
                        {v.referenced_files.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {v.referenced_files.map(f => (
                              <button
                                key={f}
                                onClick={() => onJumpToFile(f)}
                                className="rounded border border-sky-500/30 bg-sky-950/60 px-1.5 py-0.5 font-mono text-[11px] text-sky-300 hover:bg-sky-900/60 hover:text-sky-200 transition-colors"
                              >
                                {f}
                              </button>
                            ))}
                          </div>
                        ) : (
                          <span className="font-mono text-slate-500 italic">None</span>
                        )}
                      </td>
                      <td className="py-2.5 px-3 font-mono font-semibold text-slate-200">
                        {v.total_occurrences}
                      </td>
                      <td className="py-2.5 px-3">
                        {v.is_duplicate ? (
                          <span className="rounded-full border border-rose-500/40 bg-rose-950/80 px-2 py-0.5 font-mono text-[11px] font-medium text-rose-300">
                            Duplicate Declaration
                          </span>
                        ) : v.is_unused ? (
                          <span className="rounded-full border border-amber-500/40 bg-amber-950/80 px-2 py-0.5 font-mono text-[11px] font-medium text-amber-300">
                            Unused Variable
                          </span>
                        ) : isShared ? (
                          <span className="rounded-full border border-emerald-500/40 bg-emerald-950/80 px-2 py-0.5 font-mono text-[11px] font-medium text-emerald-300">
                            Cross-file Reference
                          </span>
                        ) : (
                          <span className="rounded-full border border-slate-700 bg-slate-800 px-2 py-0.5 font-mono text-[11px] font-medium text-slate-400">
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
      <div className="rounded-xl border border-sky-500/20 bg-slate-900/85 p-5 shadow-lg backdrop-blur-md">
        <h3 className="flex items-center gap-2 text-base font-semibold text-white">
          <span>Inter-File Dependencies</span>
          <span className="rounded-full border border-cyan-500/30 bg-cyan-950/80 px-2 py-0.5 font-mono text-xs text-cyan-300">
            {summary.interfile_dependencies.length}
          </span>
        </h3>
        <p className="mt-1 text-xs text-slate-400">
          Cross-file edges showing prerequisites and data dependencies between different files.
        </p>

        {summary.interfile_dependencies.length === 0 ? (
          <p className="mt-3 text-xs text-slate-500 italic">
            No dependencies crossing file boundaries found.
          </p>
        ) : (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {summary.interfile_dependencies.map((dep, idx) => (
              <div
                key={`${dep.source_node}-${dep.target_node}-${idx}`}
                className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/70 p-2.5 text-xs"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 font-mono">
                    <button
                      onClick={() => onJumpToFile(dep.source_file)}
                      className="font-medium text-cyan-400 hover:text-cyan-300 hover:underline"
                    >
                      {dep.source_file}
                    </button>
                    <svg className="h-3 w-3 shrink-0 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                    <button
                      onClick={() => onJumpToFile(dep.target_file)}
                      className="font-medium text-cyan-400 hover:text-cyan-300 hover:underline"
                    >
                      {dep.target_file}
                    </button>
                  </div>
                  <div className="mt-1 truncate font-mono text-[11px] text-slate-400">
                    Symbol: <span className="font-medium text-sky-200">{dep.symbol ?? dep.source_node}</span>
                  </div>
                </div>
                <span className="ml-2 rounded border border-cyan-500/30 bg-cyan-950/80 px-1.5 py-0.5 text-[10px] uppercase font-mono font-semibold text-cyan-300">
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
