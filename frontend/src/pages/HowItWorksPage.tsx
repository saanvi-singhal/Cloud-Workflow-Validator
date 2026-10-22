import { HREF } from '../useRoute';

// The analysis really is a pipeline, so the steps are numbered.
const STEPS: { title: string; text: string }[] = [
  {
    title: 'Read the file',
    text: 'Each format has its own parser. It records where every job, stage or resource is defined, so problems point at an exact line. Nothing is executed.',
  },
  {
    title: 'Build the dependency graph',
    text: 'An arrow from A to B means A has to come first: a job B that needs A, a stage built FROM A, a resource that references A.',
  },
  {
    title: 'Check it',
    text: 'Cycles, references to things that do not exist, parts nothing uses, and rules the target tool enforces, plus a small set of security and build-size checks.',
  },
  {
    title: 'Report',
    text: 'A verdict, every issue with its location and a suggested fix, and a ready-to-apply patch when the exact edit is known.',
  },
];

const CHECKS: { format: string; checks: string }[] = [
  {
    format: 'Terraform',
    checks:
      'Undeclared references, dependency cycles, duplicate blocks, modules split over several files, public S3 buckets, ingress open to the internet, hard-coded secrets, public databases.',
  },
  {
    format: 'GitHub Actions',
    checks:
      'Unknown or cyclic needs, keys GitHub rejects, script injection from untrusted event data, actions pinned to a branch, version numbers YAML turns into the wrong value.',
  },
  {
    format: 'Dockerfile',
    checks:
      'Unknown instructions, stages the final image never uses, mistyped stage names, running as root, unpinned images and packages, apt without -y, and build cache and image size advice.',
  },
];

const TOOLS: { title: string; text: string }[] = [
  {
    title: 'Blast radius',
    text: 'In the graph, click any item to see everything that depends on it, directly or through others: what a change to it could break.',
  },
  {
    title: 'Patches',
    text: 'Where a fix is certain, it comes as a unified diff. Copy it or download it and apply it with git apply; the tool never edits your files.',
  },
  {
    title: 'Breaking cycles',
    text: 'For a dependency cycle, the fix names the smallest set of dependencies to remove, preferring explicit depends_on and needs entries over references that pass values.',
  },
  {
    title: 'Compare versions',
    text: 'Paste an old and a new version to see the two graphs side by side, with added, removed and rewired dependencies and any new cycle.',
  },
  {
    title: 'Several files at once',
    text: 'Upload a whole Terraform module, several workflows, or a Dockerfile with the scripts it copies. Mixed mode detects each file’s format.',
  },
];

export default function HowItWorksPage() {
  return (
    <div className="mx-auto max-w-[1100px] px-4 py-8 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight text-ink">How it works</h1>
      <p className="mt-2 max-w-prose text-lg text-muted">
        Cloud Workflow Validator checks CI workflows, Dockerfiles and Terraform the way a compiler
        checks code: it reads them, builds a graph and analyses it, without running anything.
      </p>

      <ol className="mt-8 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((step, i) => (
          <li key={step.title} className="bg-surface p-5">
            <span className="font-mono text-sm text-accent">{i + 1}</span>
            <h2 className="mt-2 font-semibold text-ink">{step.title}</h2>
            <p className="mt-1 text-sm leading-relaxed text-muted">{step.text}</p>
          </li>
        ))}
      </ol>

      <h2 className="mt-12 text-xl font-semibold text-ink">What it checks</h2>
      <dl className="mt-4 divide-y divide-line-soft rounded-lg border border-line bg-surface">
        {CHECKS.map(c => (
          <div key={c.format} className="grid gap-1 p-5 sm:grid-cols-[180px_1fr] sm:gap-6">
            <dt className="font-medium text-ink">{c.format}</dt>
            <dd className="text-muted">{c.checks}</dd>
          </div>
        ))}
      </dl>

      <h2 className="mt-12 text-xl font-semibold text-ink">Tools for understanding a change</h2>
      <div className="mt-4 grid gap-x-10 gap-y-6 sm:grid-cols-2">
        {TOOLS.map(t => (
          <div key={t.title}>
            <h3 className="font-medium text-ink">{t.title}</h3>
            <p className="mt-1 text-muted">{t.text}</p>
          </div>
        ))}
      </div>

      <div className="mt-12 rounded-lg border border-line bg-surface p-6">
        <h2 className="font-semibold text-ink">What it never does</h2>
        <p className="mt-1 max-w-prose text-muted">
          It never runs your configuration, calls terraform, contacts a cloud provider or registry,
          or changes your files. Everything it reports comes from reading the text you give it.
        </p>
        <a
          href={HREF.analyze}
          className="mt-4 inline-block rounded-md bg-accent px-4 py-2 text-sm font-semibold text-on-accent hover:bg-accent-strong"
        >
          Analyze a configuration
        </a>
      </div>
    </div>
  );
}
