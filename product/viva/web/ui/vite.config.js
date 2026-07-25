import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The surface is served by the product's own stdlib HTTP server, offline, from
// a directory of static files. So: build to ../static, emit RELATIVE asset URLs
// (no host assumptions), inline nothing from a CDN, and keep the output flat
// enough that a plain file server can hand it over without configuration.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../static',
    emptyOutDir: true,
    // One JS and one CSS file: simpler for the stdlib server, and it makes the
    // committed artifact a readable diff rather than a pile of hashed chunks.
    rollupOptions: {
      output: {
        entryFileNames: 'app.js',
        chunkFileNames: 'app-[name].js',
        assetFileNames: 'app.[ext]',
      },
    },
  },
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
})
