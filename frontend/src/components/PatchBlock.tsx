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
        <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-emerald-300">
          Patch (apply with git apply)
        </span>
        <span className="flex gap-2">
          <button
            type="button"
            onClick={copy}
            className="rounded border border-emerald-500/40 px-2 py-0.5 font-mono text-[11px] text-emerald-300 hover:bg-emerald-950/50"
          >
            {copied ? 'Copied' : 'Copy patch'}
          </button>
          <button
            type="button"
            onClick={download}
            className="rounded border border-emerald-500/40 px-2 py-0.5 font-mono text-[11px] text-emerald-300 hover:bg-emerald-950/50"
          >
            Download .patch
          </button>
        </span>
      </div>
      <pre
        aria-label="Patch"
        className="mt-1.5 overflow-x-auto rounded-lg border border-slate-800 bg-slate-950 p-2.5 font-mono text-xs leading-relaxed"
      >
        {patch.split('\n').map((line, i) => (
          <div
            key={i}
            className={
              line.startsWith('+') && !line.startsWith('+++')
                ? 'text-emerald-400'
                : line.startsWith('-') && !line.startsWith('---')
                  ? 'text-rose-400'
                  : line.startsWith('@@')
                    ? 'text-sky-400'
                    : 'text-slate-400'
            }
          >
            {line || '\u00a0'}
          </div>
        ))}
      </pre>
    </div>
  );
}
