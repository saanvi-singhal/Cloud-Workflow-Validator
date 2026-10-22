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
        <span className="text-xs font-semibold text-slate-700">
          Patch (apply with git apply)
        </span>
        <span className="flex gap-2">
          <button
            type="button"
            onClick={copy}
            className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-indigo-700 hover:bg-indigo-50"
          >
            {copied ? 'Copied' : 'Copy patch'}
          </button>
          <button
            type="button"
            onClick={download}
            className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-indigo-700 hover:bg-indigo-50"
          >
            Download .patch
          </button>
        </span>
      </div>
      <pre
        aria-label="Patch"
        className="mt-1.5 overflow-x-auto rounded-lg bg-slate-900 p-2.5 font-mono text-xs leading-relaxed"
      >
        {patch.split('\n').map((line, i) => (
          <div
            key={i}
            className={
              line.startsWith('+') && !line.startsWith('+++')
                ? 'text-green-300'
                : line.startsWith('-') && !line.startsWith('---')
                  ? 'text-red-300'
                  : line.startsWith('@@')
                    ? 'text-sky-300'
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
