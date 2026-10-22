import type { AnalysisResult } from '../types';
import { ADVISOR_GROUPS, advisorItems } from '../advisor';

interface Props {
  result: AnalysisResult;
  onSelectDiagnostic: (index: number) => void;
}

/** Dockerfile build-speed and image-size findings, grouped by what they cost. */
export default function AdvisorPanel({ result, onSelectDiagnostic }: Props) {
  const items = advisorItems(result);
  const groups = ADVISOR_GROUPS.map(group => ({
    ...group,
    items: items.filter(item => group.rules.includes(item.rule)),
  })).filter(group => group.items.length > 0);
  if (groups.length === 0) return null;

  return (
    <section aria-label="Layer and cache advisor">
      <p className="max-w-prose text-sm text-muted">
        Docker reuses a cached layer only while that step and every step before it are unchanged,
        and every layer stays in the image. These findings make rebuilds slower or the image larger;
        the image still works.
      </p>
      <div className="mt-4 space-y-5">
        {groups.map(group => (
          <div key={group.title}>
            <h3 className="font-semibold text-ink">
              {group.title} <span className="font-normal text-faint">{group.items.length}</span>
            </h3>
            <p className="text-sm text-muted">{group.hint}</p>
            <ul className="mt-2 divide-y divide-line-soft rounded-md border border-line-soft">
              {group.items.map(({ index, text, diagnostic }) => (
                <li key={index}>
                  <button
                    type="button"
                    onClick={() => onSelectDiagnostic(index)}
                    className="block w-full px-3 py-2 text-left text-sm hover:bg-paper"
                  >
                    <span className="text-ink">{text}</span>
                    {diagnostic.source_location?.start_line && (
                      <span className="ml-2 text-xs text-faint">
                        line {diagnostic.source_location.start_line}
                      </span>
                    )}
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
