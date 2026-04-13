import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { nodePolyfills } from 'vite-plugin-node-polyfills';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Polyfills Node built-ins (buffer, process, etc.) that plotly.js
    // references in its browser bundle via require('buffer/')
    nodePolyfills(),
  ],
  server: {
    port: 5173,
    // Proxy API calls to the FastAPI backend during development
    proxy: {
      '/measurements': 'http://localhost:8000',
      '/analysis': 'http://localhost:8000',
      '/reports': 'http://localhost:8000',
    },
  },
  optimizeDeps: {
    // Pre-bundle plotly.js so Vite's ESM transform handles it correctly
    include: ['plotly.js'],
  },
});
