import { fileURLToPath, URL } from 'node:url'
// vitest/config, not vite: the same defineConfig plus the `test` section.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      // In dev: the frontend's /api/* requests go to uvicorn on 127.0.0.1:8000.
      // In prod FastAPI serves the frontend statics itself, no CORS needed.
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    // Components touch the DOM and localStorage — a browser-like environment
    // is required; setup.ts adds the jest-dom matchers and resets fetch.
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
    css: false,
  },
})
