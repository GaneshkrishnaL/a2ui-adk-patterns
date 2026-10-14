import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// React Native Web on Vite:
//  - every `import ... from 'react-native'` is aliased to `react-native-web`
//  - `.web.tsx` is resolved before `.tsx` (same convention Metro uses)
//  - `__DEV__` is defined because some RN libraries reference it
export default defineConfig({
  plugins: [react()],
  define: {
    __DEV__: JSON.stringify(true),
    global: 'window',
  },
  resolve: {
    alias: {
      'react-native': 'react-native-web',
    },
    extensions: ['.web.tsx', '.web.ts', '.web.js', '.tsx', '.ts', '.js', '.mjs', '.json'],
  },
  optimizeDeps: {
    include: ['react-native-web'],
  },
  server: {
    host: '0.0.0.0',
    port: 8087,
    strictPort: true,
  },
});
