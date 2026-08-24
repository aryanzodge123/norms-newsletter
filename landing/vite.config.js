import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/* Two entries, two documents. /faq is a separate static page rather than a
   client route: SPEC 15.1 (proposed) wants every word in the response body,
   and public/404.html exists specifically to defeat the SPA fallback, so a
   client route would 404 on a direct load anyway.

   The entry is a top-level faq.html rather than faq/index.html. Pages serves
   dist/faq.html at /faq directly, whereas a directory index makes /faq a 308
   to /faq/, which would have pointed the canonical tag and the sitemap at a
   redirect. scripts/prerender.mjs then fills both roots with static markup. */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5201, strictPort: true },
  build: {
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL('index.html', import.meta.url)),
        faq: fileURLToPath(new URL('faq.html', import.meta.url)),
      },
    },
  },
})
