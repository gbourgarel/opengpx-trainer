import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev: the Python backend runs on :8000; Vite proxies API + WebSocket to it.
export default defineConfig({
  plugins: [react()],
  // the 3D view (MapLibre, ~1 MB) is its own chunk, downloaded only when opened: not worth a
  // warning at every build
  build: { chunkSizeWarningLimit: 1100 },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
