import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  base: '/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    proxy: {
      '/config-agent': {
        target: 'https://endpoint-3dd6d3fb-d3e2-4ac7-8c1a-310eaeaf4d79.agentbase-runtime.aiplatform.vngcloud.vn',
        changeOrigin: true,
        secure: true,
        rewrite: path => path.replace(/^\/config-agent/, ''),
      }
    }
  },
  build: {
    chunkSizeWarningLimit: 3000,
    commonjsOptions: {
      strictRequires: ['node_modules/aws-sdk/**/*.js']
    }
  }
});
