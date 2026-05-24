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
      // В dev: запросы /api/* фронтенда → uvicorn на 127.0.0.1:8000.
      // В prod FastAPI сам отдаст статику фронта, CORS не нужен.
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
