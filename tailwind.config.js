/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './static/src/**/*.js',
  ],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Nunito', 'Golos Text', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        'bg-app':         'var(--color-bg-app)',
        'bg-surface':     'var(--color-bg-surface)',
        'bg-surface-alt': 'var(--color-bg-surface-alt)',
        'bg-sidebar':     'var(--color-bg-sidebar)',

        accent: {
          DEFAULT: '#7B5CFF',
          strong:  '#6A4CE0',
          soft:    'var(--color-accent-soft)',
          on:      '#FFFFFF',
        },
        gamification: {
          DEFAULT: '#FF9F1C',
          soft:    '#FFF3E0',
        },
        success: {
          DEFAULT: '#20C997',
          soft:    '#E6FAF5',
        },
        error: {
          DEFAULT: '#FF6B6B',
          soft:    '#FFEDED',
        },
        warning: {
          DEFAULT: '#FFB347',
          soft:    '#FFF8ED',
        },
        info: {
          DEFAULT: '#7B5CFF',
          soft:    '#EDE9FF',
        },

        'text-primary':   'var(--color-text-primary)',
        'text-secondary': 'var(--color-text-secondary)',
        'text-muted':     'var(--color-text-muted)',
        'text-inverse':   '#FFFFFF',

        stroke: {
          DEFAULT: 'var(--color-stroke)',
          strong:  'var(--color-stroke-strong)',
        },
      },
      borderRadius: {
        btn:       '12px',
        card:      '20px',
        'card-lg': '24px',
        pill:      '999px',
      },
      boxShadow: {
        soft:        '0 10px 30px rgba(123, 92, 255, 0.08)',
        card:        '0 4px 20px rgba(123, 92, 255, 0.06)',
        'card-hover':'0 8px 30px rgba(123, 92, 255, 0.12)',
        accent:      '0 8px 24px rgba(123, 92, 255, 0.20)',
        'accent-glow':'0 0 40px rgba(123, 92, 255, 0.15)',
        fab:         '0 6px 20px rgba(123, 92, 255, 0.25)',
        toast:       '0 10px 30px rgba(0, 0, 0, 0.12)',
        modal:       '0 20px 60px rgba(0, 0, 0, 0.2)',
      },
      animation: {
        'fade-in':     'fade-in 0.3s ease-out',
        'slide-up':    'slide-up 0.3s ease-out',
        'slide-down':  'slide-down 0.3s ease-out',
        'pulse-glow':  'pulse-glow 2s ease-in-out infinite',
        'streak-fire': 'streak-fire 1.5s ease-in-out infinite',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to:   { opacity: '1' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-down': {
          from: { opacity: '0', transform: 'translateY(-12px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 12px rgba(123, 92, 255, 0.15)' },
          '50%':      { boxShadow: '0 0 24px rgba(123, 92, 255, 0.35)' },
        },
        'streak-fire': {
          '0%, 100%': { transform: 'scale(1)', filter: 'brightness(1)' },
          '50%':      { transform: 'scale(1.15)', filter: 'brightness(1.2)' },
        },
      },
    },
  },
  plugins: [],
};
