import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api/* to the FastAPI backend so the browser makes
// same-origin requests (no CORS) and SSE works through the proxy.
// The /api prefix is stripped before forwarding (backend routes are /auth, /runs).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
