import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Only under Vitest: the opt-in end-to-end test (src/e2e.test.tsx) reads
  // ../examples. The dev server keeps Vite's default of serving frontend/ only.
  server: process.env.VITEST ? { fs: { allow: ['..'] } } : undefined,
})
