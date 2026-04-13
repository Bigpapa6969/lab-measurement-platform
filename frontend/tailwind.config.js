/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Base chrome — oscilloscope dark UI
        scope: {
          bg:      '#080c12',   // near-black canvas
          surface: '#0f1520',   // panel background
          panel:   '#141c2b',   // raised surface
          border:  '#1e2d42',   // subtle dividers
          hover:   '#1a2540',   // interactive hover
        },
        // Waveform channel colours (classic scope convention)
        ch1:  '#f0c040',   // golden yellow
        ch2:  '#40c8f0',   // cyan
        ch3:  '#f040a8',   // magenta
        ch4:  '#40e878',   // green
        // Status colours
        pass: '#3fb950',
        fail: '#f85149',
        warn: '#d29922',
        // Text hierarchy
        ink: {
          primary:   '#e6edf3',
          secondary: '#8b949e',
          muted:     '#484f58',
        },
        // Accent
        accent: '#58a6ff',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Cascadia Code', 'Consolas', 'monospace'],
        ui:   ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
