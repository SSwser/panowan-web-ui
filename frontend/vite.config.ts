import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backendTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'
const proxyRoutes = ['/api', '/jobs', '/generate', '/upscale', '/health']

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    watch: {
      usePolling: process.env.CHOKIDAR_USEPOLLING === '1',
    },
    proxy: Object.fromEntries(proxyRoutes.map((route) => [route, backendTarget])),
  },
})
