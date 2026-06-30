import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
  },
  // No manualChunks: route-based code-splitting (React.lazy in App.tsx) lets
  // Rollup automatically isolate each lazy route's unique dependencies — the
  // heavy libs (x-data-grid, query-builder, react-json-view, zxcvbn) end up in
  // chunks fetched only when their route is visited. Forcing those libs into
  // manual chunks instead hoists them into the entry's static import graph
  // (they get <link rel="modulepreload">'d on first load), which defeats the
  // split. Leave chunking to Rollup's dynamic-import analysis.
})
