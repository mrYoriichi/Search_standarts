import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
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
})
