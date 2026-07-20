// @ts-check
import { defineConfig } from 'astro/config';

// The ONLY place the site's absolute URL and base path are defined (SPEC 6.6,
// CLAUDE.md rule 6). Every self URL on the site derives from these two values:
// canonical links, OG tags, feed links, and audio enclosure URLs. The
// pre-launch migration (SPEC section 13) changes these two values and nothing
// else. A hardcoded self URL anywhere is a bug the milestone-verify gate fails.
export default defineConfig({
  site: 'https://aryanzodge123.github.io',
  base: '/norms-newsletter',
  trailingSlash: 'always',
  build: {
    // Emit /path/index.html so trailing-slash routes resolve on GitHub Pages.
    format: 'directory',
  },
});
