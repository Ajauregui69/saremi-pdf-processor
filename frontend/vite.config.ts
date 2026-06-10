import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5175,
    host: '0.0.0.0',
    watch: {
      usePolling: true,
      interval: 1000,
    },
    hmr: {
      host: 'localhost',
      clientPort: 5175,
    },
    proxy: {
      '/admin': process.env.SAREMI_BACKEND_URL || 'http://localhost:8000',
      '/v1': process.env.SAREMI_BACKEND_URL || 'http://localhost:8000',
      '/health': process.env.SAREMI_BACKEND_URL || 'http://localhost:8000',
    },
  },
})
