import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api/chatops': {
        target: process.env.VITE_DEV_CHATOPS_PROXY_TARGET || 'http://localhost:8001',
        changeOrigin: true
      },
      '/api/rca': {
        target: process.env.VITE_DEV_RCA_PROXY_TARGET || 'http://localhost:8002',
        changeOrigin: true
      },
      '/api/predict': {
        target: process.env.VITE_DEV_PREDICT_PROXY_TARGET || 'http://localhost:8003',
        changeOrigin: true
      }
    }
  }
})
