// Grouping of the backend's Dockerfile layer and cache advisor findings
// (backend/app/rules/dockerfile_advisor.py) by what they cost.
import type { AnalysisResult, Diagnostic } from './types';

export const ADVISOR_GROUPS: { title: string; hint: string; rules: string[] }[] = [
  {
    title: 'Cache order',
    hint: 'Steps that make Docker rebuild layers it could have reused.',
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
    title: 'Multi-stage builds',
    hint: 'Build tools that end up in the final image.',
    rules: ['DF_MULTI_STAGE_OPPORTUNITY', 'DF_FINAL_STAGE_SDK_IMAGE'],
  },
];

const ADVISOR_RULES = new Set(ADVISOR_GROUPS.flatMap(g => g.rules));

/** "[DF_PIP_NO_CACHE_DIR] pip keeps ..." -> ["DF_PIP_NO_CACHE_DIR", "pip keeps ..."] */
export function splitRule(message: string): [string | null, string] {
  const match = /^\[([A-Z0-9_]+)\]\s*/.exec(message);
  return match ? [match[1], message.slice(match[0].length)] : [null, message];
}

export interface AdvisorItem {
  index: number;
  rule: string;
  text: string;
  diagnostic: Diagnostic;
}

export function advisorItems(result: AnalysisResult): AdvisorItem[] {
  return result.diagnostics.flatMap((diagnostic, index) => {
    const [rule, text] = splitRule(diagnostic.message);
    return rule && ADVISOR_RULES.has(rule) ? [{ index, rule, text, diagnostic }] : [];
  });
}
