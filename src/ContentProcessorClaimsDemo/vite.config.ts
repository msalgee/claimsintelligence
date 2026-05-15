import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const apiTarget = env.VITE_API_BASE_URL || 'http://localhost:8000';

  return {
    plugins: [react()],
    resolve: {
      dedupe: ['keyborg'],
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          secure: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            'vendor-react': ['react', 'react-dom', 'react-router-dom'],
            'vendor-fluent': ['@fluentui/react-components', '@fluentui/react-icons'],
            'vendor-msal': ['@azure/msal-browser', '@azure/msal-react'],
            'vendor-motion': ['framer-motion'],
            'vendor-markdown': ['react-markdown'],
          },
        },
      },
    },
  };
});
