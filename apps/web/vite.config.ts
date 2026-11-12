import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE_PATH || '/',
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': process.env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8876',
      '/health': process.env.VITE_DEV_API_TARGET || 'http://127.0.0.1:8876',
    },
  },
});
