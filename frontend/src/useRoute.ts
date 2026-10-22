import { useEffect, useState } from 'react';

export type Route = 'analyze' | 'compare' | 'how-it-works';

const ROUTES: Record<string, Route> = {
  '': 'analyze',
  '#/': 'analyze',
  '#/analyze': 'analyze',
  '#/compare': 'compare',
  '#/how-it-works': 'how-it-works',
};

export const HREF: Record<Route, string> = {
  analyze: '#/analyze',
  compare: '#/compare',
  'how-it-works': '#/how-it-works',
};

function current(): Route {
  return ROUTES[window.location.hash] ?? 'analyze';
}

/** Hash-based pages (#/compare), so links, reloads and the back button work. */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(current);
  useEffect(() => {
    const onChange = () => {
      setRoute(current());
      window.scrollTo?.({ top: 0 });
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}
