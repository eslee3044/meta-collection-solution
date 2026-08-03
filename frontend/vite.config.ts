import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiProxy = { '/api': 'http://localhost:8000' }

export default defineConfig({
  plugins: [react()],
  build: { emptyOutDir: false },
  server: {
    port: 5173,
    proxy: apiProxy,
  },
  preview: {
    port: 8081,
    proxy: apiProxy,
  },
})
