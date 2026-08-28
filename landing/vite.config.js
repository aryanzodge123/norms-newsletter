import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/* Four entries, four documents. /faq and /blog are separate static pages
   rather than client routes: SPEC 15.1 (proposed) wants every word in the
   response body, and public/404.html exists specifically to defeat the SPA
   fallback, so a client route would 404 on a direct load anyway.

   Each entry is a top-level .html rather than a directory index. Pages serves
   dist/faq.html at /faq directly, whereas faq/index.html makes /faq a 308 to
   /faq/, which would have pointed the canonical tag and the sitemap at a
   redirect. scripts/prerender.mjs then fills every root with static markup. */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5201, strictPort: true },
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('index.html', import.meta.url)),
        faq: fileURLToPath(new URL('faq.html', import.meta.url)),
        blog: fileURLToPath(new URL('blog.html', import.meta.url)),
        /* A post lives under the index it is listed on. dist/blog.html
           still answers /blog, because there is no blog/index.html to
           turn that into a redirect. */
        post: fileURLToPath(new URL('blog/put-my-phone-down.html', import.meta.url)),
      },
    },
  },
})
