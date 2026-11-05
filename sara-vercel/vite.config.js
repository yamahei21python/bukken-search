import { defineConfig } from 'vite'

export default defineConfig({
  base: '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: 'index.html',
      output: {
        assetFileNames: (assetInfo) => {
          let extType = assetInfo.name.split('.').pop()
          if (/png|jpe?g|svg|gif|tif|tiff|bmp|ico/.test(extType)) {
            extType = 'images'
          }
          if (/css/.test(extType)) {
            extType = 'styles'
          }
          return `assets/${assetInfo.name.split('/').pop()}`
        },
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].css'
      }
    }
  },
  server: {
    open: true
  }
})