import type { AnalysisResult } from '../types';

// Rule ids of the backend's layer and cache advisor (dockerfile_advisor.py).
const GROUPS: { title: string; hint: string; rules: string[] }[] = [
  {
    title: 'Cache order',
    hint: 'Steps that make Docker rebuild layers it could reuse.',
    rules: ['DF_VOLATILE_ARG_EARLY', 'DF_PACKAGES_AFTER_SOURCE', 'DF_COPY_ALL_BEFORE_INSTALL'],
  },
  {
    title: 'Image size',
    hint: 'Files left in layers that the running container never needs.',
    rules: [
      'DF_APT_NO_RECOMMENDS',
      'DF_APT_LISTS_NOT_REMOVED',
      'DF_PIP_NO_CACHE_DIR',
      'DF_APK_NO_CACHE',
      'DF_CLEANUP_IN_SEPARATE_LAYER',
      'DF_CONSECUTIVE_RUN',
    ],
  },
  {
    title: 'Multi-stage',
    hint: 'Build tools that end up in the final image.',
    rules: ['DF_MULTI_STAGE_OPPORTUNITY', 'DF_FINAL_STAGE_SDK_IMAGE'],
  },
];

function ruleOf(message: string): string | null {
  const match = /^\[([A-Z0-9_]+)\]/.exec(message);
  return match ? match[1] : null;
}

interface Props {
  result: AnalysisResult;
  onSelectDiagnostic: (index: number) => void;
}

/** Groups the Dockerfile build-speed and image-size findings by what they cost. */
export default function AdvisorPanel({ result, onSelectDiagnostic }: Props) {
  const groups = GROUPS.map(group => ({
    ...group,
    items: result.diagnostics
      .map((d, index) => ({ d, index, rule: ruleOf(d.message) }))
      .filter(x => x.rule !== null && group.rules.includes(x.rule)),
  })).filter(group => group.items.length > 0);
  if (groups.length === 0) return null;

  return (
    <section aria-label="Layer and cache advisor" className="mt-6">
      <h2 className="font-mono text-base font-semibold uppercase tracking-wider text-white">
        Layer &amp; cache advisor
      </h2>
      <div className="mt-2 grid gap-3 sm:grid-cols-3">
        {groups.map(group => (
          <div key={group.title} className="rounded-lg border border-sky-500/30 bg-slate-950/60 p-3">
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-xs font-semibold uppercase tracking-wide text-cyan-300">
                {group.title}
              </span>
              <span className="font-mono text-lg font-bold text-white">{group.items.length}</span>
            </div>
            <p className="mt-1 text-[11px] text-slate-400">{group.hint}</p>
            <ul className="mt-2 space-y-1">
              {group.items.map(({ index, rule, d }) => (
                <li key={index}>
                  <button
                    type="button"
                    onClick={() => onSelectDiagnostic(index)}
                    className="text-left font-mono text-[11px] text-sky-300 hover:underline"
                  >
                    {rule}
                    {d.source_location?.start_line ? ` · line ${d.source_location.start_line}` : ''}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
