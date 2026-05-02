/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './static/src/**/*.js',
    './app/theory/routes.py',
  ],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Golos Text"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        /* Airy Dark tokens — совпадает с boostudy2.0_examples/prepod/dark_mode*.html */
        dark: {
          bg:     '#09090B',
          card:   '#131316',
          inner:  '#18181B',
          border: '#27272A',
          text:   '#FAFAFA',
          muted:  '#A1A1AA',
        },
        boo: {
          bg:           '#FFFFFF',
          surface:      '#FFFFFF',
          primary:      '#8B5CF6',
          primaryHover: '#6A4CE5',
          cyan:         '#22D3EE',
          cyanLight:    '#ECFEFF',
          coral:        '#FB7185',
          accent:       '#FBBF24',
          textMain:     '#1E293B',
          textMuted:    '#64748B',
        },
        // Semantic aliases used by component classes
        'bg-app':         'var(--color-bg-app)',
        'bg-surface':     'var(--color-bg-surface)',
        'bg-surface-alt': 'var(--color-bg-surface-alt)',
        accent: {
          DEFAULT: '#8B5CF6',
          strong:  '#6A4CE5',
          soft:    'var(--color-accent-soft)',
          on:      '#FFFFFF',
        },
        gamification: { DEFAULT: '#FBBF24', soft: '#FFFAE6' },
        success:      { DEFAULT: '#22D3EE', soft: '#ECFEFF' },
        error:        { DEFAULT: '#FB7185', soft: '#FFF1F5' },
        /* Оранжевый «зона риска» как в эталоне (orange-500), не amber #FBBF24 */
        warning:      { DEFAULT: '#F97316', soft: '#FFF7ED' },
        info:         { DEFAULT: '#8B5CF6', soft: '#EDE9FF' },
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
        '3xl':     '24px',
        '4xl':     '28px',
        pill:      '999px',
      },
      boxShadow: {
        'glass-dark':
          '0 4px 30px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.05)',
        'nav-dark':
          '0 10px 30px rgba(0, 0, 0, 0.6), inset 0 -1px 0 rgba(255, 255, 255, 0.05)',
        'neon-primary': '0 0 40px rgba(139, 92, 246, 0.2)',
        'neon-orange':  '0 0 20px rgba(249, 115, 22, 0.1)',
        'neon-red':     '0 0 20px rgba(251, 113, 133, 0.15)',
        tactile:       '0 8px 24px -4px rgba(15, 23, 42, 0.05)',
        'tactile-hover':'0 20px 40px -8px rgba(139, 92, 246, 0.15)',
        'ghost-glow':   '0 0 20px rgba(139, 92, 246, 0.3)',
        'purple-card':  '0 15px 30px -10px rgba(139, 92, 246, 0.4)',
        nav:           '0 4px 20px rgba(15, 23, 42, 0.05)',
        input:         'inset 0 2px 4px rgba(0, 0, 0, 0.02)',
        'inner-soft':  'inset 0 2px 10px rgba(0, 0, 0, 0.02)',
        sm:            '0 1px 3px rgba(15, 23, 42, 0.06)',
        // Legacy aliases
        soft:          '0 8px 24px -4px rgba(15, 23, 42, 0.05)',
        card:          '0 8px 24px -4px rgba(15, 23, 42, 0.05)',
        'card-hover':  '0 20px 40px -8px rgba(139, 92, 246, 0.15)',
        accent:        '0 8px 24px rgba(123, 92, 255, 0.20)',
        'accent-glow': '0 0 40px rgba(123, 92, 255, 0.15)',
        fab:           '0 6px 20px rgba(123, 92, 255, 0.25)',
        toast:         '0 10px 30px rgba(0, 0, 0, 0.12)',
        modal:         '0 20px 60px rgba(0, 0, 0, 0.15)',
      },
      animation: {
        'fade-in':     'fade-in 0.3s ease-out',
        'slide-up':    'slide-up 0.3s ease-out',
        'slide-down':  'slide-down 0.3s ease-out',
        'pulse-glow':  'pulse-glow 2s ease-in-out infinite',
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
      },
    },
  },
  plugins: [],
};
