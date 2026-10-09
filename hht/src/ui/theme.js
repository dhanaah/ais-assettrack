// Themes for the HHT. Values are copied into C / GRAD / S in place so every screen re-styles on next render. Developed by DT
export const THEMES = {
  glass: { name: 'Glass (light)', dark: false,
    C: { bg: '#eef2ff', card: 'rgba(255,255,255,0.62)', fg: '#0f172a', mute: '#475569', accent: '#1e3a8a', violet: '#dc2626', ok: '#059669', warn: '#dc2626', amber: '#d97706', line: 'rgba(255,255,255,0.8)', sky: '#0ea5e9', input: 'rgba(255,255,255,0.85)', inputBorder: 'rgba(30,58,138,0.15)' },
    GRAD: { screen: ['#e0e7ff', '#ecfeff', '#fdf2f8'], header: ['#1e3a8a', '#7c2d8f', '#dc2626'], btn: ['#1e3a8a', '#dc2626'], ok: ['#059669', '#10b981'], amber: ['#d97706', '#f59e0b'], red: ['#dc2626', '#f43f5e'], blobs: ['rgba(99,102,241,0.18)', 'rgba(14,165,233,0.16)', 'rgba(244,114,182,0.16)'] }, blur: 40, blurTint: 'light' },
  glassDark: { name: 'Glass (dark)', dark: true,
    C: { bg: '#0b1020', card: 'rgba(17,24,39,0.62)', fg: '#e5e7eb', mute: '#9ca3af', accent: '#60a5fa', violet: '#f87171', ok: '#34d399', warn: '#f87171', amber: '#fbbf24', line: 'rgba(255,255,255,0.14)', sky: '#38bdf8', input: 'rgba(15,23,42,0.75)', inputBorder: 'rgba(255,255,255,0.18)' },
    GRAD: { screen: ['#0b1020', '#111a3a', '#1f0f2e'], header: ['#1e3a8a', '#6d28d9', '#be123c'], btn: ['#2563eb', '#db2777'], ok: ['#059669', '#10b981'], amber: ['#d97706', '#f59e0b'], red: ['#dc2626', '#f43f5e'], blobs: ['rgba(79,70,229,0.35)', 'rgba(6,182,212,0.25)', 'rgba(219,39,119,0.25)'] }, blur: 30, blurTint: 'dark' },
  classic: { name: 'AIS classic', dark: false,
    C: { bg: '#f4f6f8', card: '#ffffff', fg: '#111827', mute: '#4b5563', accent: '#1e3a8a', violet: '#dc2626', ok: '#047857', warn: '#b91c1c', amber: '#b45309', line: '#e5e7eb', sky: '#0369a1', input: '#ffffff', inputBorder: '#cbd5e1' },
    GRAD: { screen: ['#f4f6f8', '#f4f6f8', '#f4f6f8'], header: ['#1e3a8a', '#1e3a8a', '#1e3a8a'], btn: ['#1e3a8a', '#1e3a8a'], ok: ['#047857', '#047857'], amber: ['#b45309', '#b45309'], red: ['#b91c1c', '#b91c1c'], blobs: ['transparent', 'transparent', 'transparent'] }, blur: 0, blurTint: 'light' },
  outdoor: { name: 'Outdoor (high contrast)', dark: false,
    C: { bg: '#ffffff', card: '#ffffff', fg: '#000000', mute: '#1f2937', accent: '#0b2a6f', violet: '#b00020', ok: '#006b3c', warn: '#b00020', amber: '#9a4d00', line: '#111827', sky: '#0b2a6f', input: '#ffffff', inputBorder: '#111827' },
    GRAD: { screen: ['#ffffff', '#ffffff', '#ffffff'], header: ['#0b2a6f', '#0b2a6f', '#0b2a6f'], btn: ['#0b2a6f', '#0b2a6f'], ok: ['#006b3c', '#006b3c'], amber: ['#9a4d00', '#9a4d00'], red: ['#b00020', '#b00020'], blobs: ['transparent', 'transparent', 'transparent'] }, blur: 0, blurTint: 'light' },
};
export const THEME_KEYS = Object.keys(THEMES);
