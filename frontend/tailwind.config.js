/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#0E4D8C', dark: '#0B3B6C', light: '#DCE7F4' },
        body: '#23303A',
        muted: '#6B7280',
        surface: { alt: '#F5F7FB' },
        line: '#E5E7EB',
        code: '#F1F5F9',
        status: {
          green: '#16A34A',
          amber: '#F59E0B',
          red: '#DC2626',
          grey: '#94A3B8',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SF Mono', 'Consolas', 'monospace'],
      },
      keyframes: {
        pulseRed: {
          '0%,100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
        slideIn: {
          from: { transform: 'translateX(100%)' },
          to: { transform: 'translateX(0)' },
        },
        fadeIn: {
          from: { opacity: '0', transform: 'translateY(-2px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        // Soft outward ring used for the Planning (unacknowledged) pulse —
        // applied to the dashboard pill AND the Planning Board Unscheduled card.
        pulseRing: {
          '0%':   { boxShadow: '0 0 0 0px rgba(6, 182, 212, 0.55)' },
          '70%':  { boxShadow: '0 0 0 12px rgba(6, 182, 212, 0)' },
          '100%': { boxShadow: '0 0 0 0px rgba(6, 182, 212, 0)' },
        },
      },
      animation: {
        pulseRed: 'pulseRed 2s ease-in-out infinite',
        slideIn: 'slideIn 0.25s ease-out',
        fadeIn: 'fadeIn 200ms ease-out',
        pulseRing: 'pulseRing 2s ease-out infinite',
      },
    },
  },
  plugins: [],
}
