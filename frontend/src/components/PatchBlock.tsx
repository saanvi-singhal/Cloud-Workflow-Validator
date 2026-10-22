import { useState } from 'react';

interface Props {
  patch: string;
  /** Used for the downloaded file name, e.g. "DF_APT_MISSING_YES:3". */
  id: string;
}

/** A ready-to-apply unified diff with copy and download buttons. */
export default function PatchBlock({ patch, id }: Props) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(patch);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([patch], { type: 'text/x-diff' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${id.replace(/[^\w.-]+/g, '_')}.patch`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold text-muted">Patch (apply with git apply)</span>
        <span className="flex gap-2">
          <button
            type="button"
            onClick={copy}
            className="rounded border border-line bg-surface px-2 py-0.5 text-xs text-accent-strong hover:bg-accent-soft"
          >
            {copied ? 'Copied' : 'Copy patch'}
          </button>
          <button
            type="button"
            onClick={download}
            className="rounded border border-line bg-surface px-2 py-0.5 text-xs text-accent-strong hover:bg-accent-soft"
          >
            Download .patch
          </button>
        </span>
      </div>
      <pre
        aria-label="Patch"
        className="mt-1.5 overflow-x-auto rounded-md bg-code p-2.5 text-code-text font-mono text-xs leading-relaxed"
      >
        {patch.split('\n').map((line, i) => (
          <div
            key={i}
            className={
              line.startsWith('+') && !line.startsWith('+++')
                ? 'text-code-add'
                : line.startsWith('-') && !line.startsWith('---')
                  ? 'text-code-del'
                  : line.startsWith('@@')
                    ? 'text-code-hunk'
                    : 'text-code-text opacity-70'
            }
          >
            {line || '\u00a0'}
          </div>
        ))}
      </pre>
    </div>
  );
}
