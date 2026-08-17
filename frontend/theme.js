/* ==========================================================================
   Conductor — UI theme engine (loaded before app.js)
   - THEME_DEFAULTS : the custom design-token blob (matches data/ui.json)
   - THEME_PRESETS  : the 6 builtin Hermes Desktop themes (dark + light)
   - TOKEN_SCHEMA   : drives the Appearance token editor
   - applyUiTokens  : blob → CSS custom properties on :root
   ========================================================================== */
'use strict';

/* ---------- shared meta (non-color tokens) ---------- */
const META_DARK = {
  opacity: { subtle: 0.08, muted: 0.16, half: 0.5, strong: 0.72, solid: 1 },
  density: { scale: 1, unit: 4, controlHeight: 36, padding: 12 },
  edges: { radius: 4, borderWidth: 1, borderColor: 'rgba(255,255,255,0.12)' },
  highlights: {
    topEdge: 'rgba(255,255,255,0.18)',
    glow: 'rgba(110,86,207,0.45)',
    selection: 'rgba(110,86,207,0.35)',
  },
  elevation: {
    1: '0 1px 2px rgba(0,0,0,0.35)',
    2: '0 6px 16px rgba(0,0,0,0.45)',
    3: '0 24px 64px rgba(0,0,0,0.55)',
  },
  depth: { perspective: 1200, layerOffset: 8, innerShadow: 'inset 0 2px 8px rgba(0,0,0,0.45)' },
  gloss: { intensity: 0.35, angle: 115, sheen: 'rgba(255,255,255,0.22)', blend: 'overlay' },
  motion: { duration: 200, easing: 'cubic-bezier(0.2,0,0,1)' },
  blur: { backdrop: 18 },
};

const META_LIGHT = {
  opacity: { subtle: 0.06, muted: 0.12, half: 0.5, strong: 0.72, solid: 1 },
  density: { scale: 1, unit: 4, controlHeight: 36, padding: 12 },
  edges: { radius: 4, borderWidth: 1, borderColor: 'rgba(15,23,42,0.14)' },
  highlights: {
    topEdge: 'rgba(255,255,255,0.85)',
    glow: 'rgba(0,83,253,0.22)',
    selection: 'rgba(0,83,253,0.18)',
  },
  elevation: {
    1: '0 1px 2px rgba(15,23,42,0.08)',
    2: '0 6px 16px rgba(15,23,42,0.10)',
    3: '0 24px 64px rgba(15,23,42,0.16)',
  },
  depth: { perspective: 1200, layerOffset: 8, innerShadow: 'inset 0 2px 8px rgba(15,23,42,0.08)' },
  gloss: { intensity: 0.18, angle: 115, sheen: 'rgba(255,255,255,0.9)', blend: 'overlay' },
  motion: { duration: 200, easing: 'cubic-bezier(0.2,0,0,1)' },
  blur: { backdrop: 18 },
};

const HEADER_FONT = { family: 'Inter Tight, sans-serif', weight: 650, tracking: '-0.02em' };
const BODY_FONT = { family: 'Inter, sans-serif', weight: 400, size: 15, lineHeight: 1.55 };
const CODE_FONT_DEFAULT = { family: 'JetBrains Mono, monospace', size: 13, ligatures: true };

function toRgba(v, a) {
  if (typeof v !== 'string' || v[0] !== '#') return v;
  const h = v.replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const n = parseInt(full.slice(0, 6), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

/* Build a full blob for one preset palette. */
function preset(p) {
  const meta = p.light ? META_LIGHT : META_DARK;
  return {
    theme: p.name,
    mode: p.light ? 'light' : 'dark',
    gradient1: p.grad1,
    gradient2: p.grad2,
    background1: p.bg,
    background2: p.bg2,
    surface: { base: p.base, raised: p.raised, overlay: toRgba(p.raised, 0.72) },
    function: { primary: p.primary, secondary: p.secondary, success: p.success, warning: p.warning, danger: p.danger, info: p.info },
    colorFont: { heading: p.heading, body: p.body, muted: p.muted, link: p.link, code: p.code },
    headerFont: p.headerFont || HEADER_FONT,
    bodyFont: p.bodyFont || BODY_FONT,
    codeFont: p.codeFont || CODE_FONT_DEFAULT,
    onPrimary: p.onPrimary || '#FFFFFF',
    ...meta,
  };
}

/* ---------- the 6 Hermes Desktop themes (values from src/themes/presets.ts) ---------- */
const THEME_PRESETS = {
  nous: {
    label: 'Nous',
    desc: 'Glass neutrals with Nous blue accents',
    dark: preset({
      name: 'nous', light: false,
      bg: '#0D2F86', bg2: '#183F9A', base: '#12378F', raised: '#123A96',
      primary: '#0053FD', secondary: '#1B45A4', success: '#55A583', warning: '#E3A008', danger: '#C0473A', info: '#6F9BA6',
      heading: '#FFE6CB', body: '#FFE6CB', muted: '#B5C7F3', link: '#8FB8FF', code: '#D6E4FF',
      border: '#3158AD', onPrimary: '#FFFFFF',
      grad1: 'linear-gradient(135deg, #0053FD 0%, #8B7CFF 100%)',
      grad2: 'radial-gradient(ellipse at top, #FFE6CB 0%, transparent 100%)',
      codeFont: { family: '"Courier Prime", monospace', size: 13, ligatures: false },
    }),
    light: preset({
      name: 'nous', light: true,
      bg: '#F8FAFF', bg2: '#F3F7FF', base: '#FFFFFF', raised: '#FFFFFF',
      primary: '#0053FD', secondary: '#EAF1FE', success: '#2FA36B', warning: '#B7791F', danger: '#C72E4D', info: '#0053FD',
      heading: '#17171A', body: '#17171A', muted: '#666678', link: '#0053FD', code: '#242432',
      border: 'color-mix(in srgb, #0053FD 22%, #FFFFFF)', onPrimary: '#FCFCFC',
      grad1: 'linear-gradient(135deg, #0053FD 0%, #8B7CFF 100%)',
      grad2: 'radial-gradient(ellipse at top, #BBD4FF 0%, transparent 100%)',
      codeFont: { family: '"Courier Prime", monospace', size: 13, ligatures: false },
    }),
  },
  dune: {
    label: 'Solarized Dune',
    desc: 'Warm desert sand with a blue gradient lift',
    dark: preset({
      name: 'dune', light: false,
      bg: '#1A1712', bg2: '#241F18', base: '#201B15', raised: '#262019',
      primary: '#5B9CFF', secondary: '#2E271E', success: '#55A583', warning: '#E3A008', danger: '#C0473A', info: '#6F9BA6',
      heading: '#F0E8D8', body: '#E5DCC8', muted: '#9A8E78', link: '#7FB1FF', code: '#D8CBB2',
      onPrimary: '#0D1117',
      grad1: 'linear-gradient(135deg, #2563EB 0%, #7C3AED 100%)',
      grad2: 'radial-gradient(ellipse at top, #FFD98A 0%, transparent 100%)',
      codeFont: { family: '"JetBrains Mono", monospace', size: 13, ligatures: true },
    }),
    light: preset({
      name: 'dune', light: true,
      bg: '#FAF6ED', bg2: '#F3ECDD', base: '#FFFFFF', raised: '#FFFFFF',
      primary: '#0066D1', secondary: '#E8E1D2', success: '#2FA36B', warning: '#B7791F', danger: '#C72E4D', info: '#0066D1',
      heading: '#1F2937', body: '#334155', muted: '#7A8A9E', link: '#0066D1', code: '#334155',
      onPrimary: '#FFFFFF',
      grad1: 'linear-gradient(135deg, #0066D1 0%, #4B8BFF 100%)',
      grad2: 'radial-gradient(ellipse at top, #FFE8C2 0%, transparent 100%)',
      codeFont: { family: '"JetBrains Mono", monospace', size: 13, ligatures: true },
    }),
  },
  midnight: {
    label: 'Midnight',
    desc: 'Deep blue-violet with cool accents',
    dark: preset({
      name: 'midnight', light: false,
      bg: '#08081c', bg2: '#13133a', base: '#0d0d28', raised: '#0f0f2e',
      primary: '#8b80e8', secondary: '#1a1a4a', success: '#55A583', warning: '#E3A008', danger: '#b03060', info: '#8b80e8',
      heading: '#ddd6ff', body: '#ddd6ff', muted: '#7c7ab0', link: '#a99eff', code: '#c4bff0',
      border: '#1e1e52', onPrimary: '#08081c',
      grad1: 'linear-gradient(135deg, #8b80e8 0%, #3b2f8f 100%)',
      grad2: 'radial-gradient(ellipse at top, #8b80e8 0%, transparent 100%)',
      codeFont: { family: '"JetBrains Mono", monospace', size: 13, ligatures: true },
    }),
    light: preset({
      name: 'midnight', light: true,
      bg: '#F4F3FF', bg2: '#EAE7FF', base: '#FFFFFF', raised: '#FFFFFF',
      primary: '#6b5fd6', secondary: '#EDEBFF', success: '#2FA36B', warning: '#B7791F', danger: '#b03060', info: '#6b5fd6',
      heading: '#1a1838', body: '#1a1838', muted: '#6f6b9e', link: '#6b5fd6', code: '#2c2850',
      border: '#D8D4F5', onPrimary: '#FFFFFF',
      grad1: 'linear-gradient(135deg, #8b80e8 0%, #5a4fd0 100%)',
      grad2: 'radial-gradient(ellipse at top, #D8D4F5 0%, transparent 100%)',
      codeFont: { family: '"JetBrains Mono", monospace', size: 13, ligatures: true },
    }),
  },
  ember: {
    label: 'Ember',
    desc: 'Warm crimson and bronze — forge vibes',
    dark: preset({
      name: 'ember', light: false,
      bg: '#160800', bg2: '#2a1408', base: '#1e0e04', raised: '#221008',
      primary: '#d97316', secondary: '#341800', success: '#55A583', warning: '#E3A008', danger: '#c43010', info: '#d97316',
      heading: '#ffd8b0', body: '#ffd8b0', muted: '#aa7a56', link: '#f0a050', code: '#f0c090',
      border: '#3a1c08', onPrimary: '#160800',
      grad1: 'linear-gradient(135deg, #d97316 0%, #7a3410 100%)',
      grad2: 'radial-gradient(ellipse at top, #E3A008 0%, transparent 100%)',
      codeFont: { family: '"IBM Plex Mono", monospace', size: 13, ligatures: true },
    }),
    light: preset({
      name: 'ember', light: true,
      bg: '#FFF8F2', bg2: '#FBEAD9', base: '#FFFFFF', raised: '#FFFFFF',
      primary: '#c25e10', secondary: '#FDEBD8', success: '#2FA36B', warning: '#B7791F', danger: '#c43010', info: '#c25e10',
      heading: '#2a1506', body: '#2a1506', muted: '#8a6240', link: '#c25e10', code: '#4a2a10',
      border: '#F0DCC8', onPrimary: '#FFFFFF',
      grad1: 'linear-gradient(135deg, #d97316 0%, #b04f0c 100%)',
      grad2: 'radial-gradient(ellipse at top, #FFD9B0 0%, transparent 100%)',
      codeFont: { family: '"IBM Plex Mono", monospace', size: 13, ligatures: true },
    }),
  },
  mono: {
    label: 'Mono',
    desc: 'Clean grayscale — minimal and focused',
    dark: preset({
      name: 'mono', light: false,
      bg: '#0e0e0e', bg2: '#1e1e1e', base: '#141414', raised: '#181818',
      primary: '#9a9a9a', secondary: '#262626', success: '#55A583', warning: '#C9A24B', danger: '#a84040', info: '#9a9a9a',
      heading: '#eaeaea', body: '#eaeaea', muted: '#808080', link: '#b8b8b8', code: '#d8d8d8',
      border: '#2a2a2a', onPrimary: '#0e0e0e',
      grad1: 'linear-gradient(135deg, #9a9a9a 0%, #3a3a3a 100%)',
      grad2: 'radial-gradient(ellipse at top, #444 0%, transparent 100%)',
      codeFont: CODE_FONT_DEFAULT,
    }),
    light: preset({
      name: 'mono', light: true,
      bg: '#F7F7F7', bg2: '#ECECEC', base: '#FFFFFF', raised: '#FFFFFF',
      primary: '#555555', secondary: '#E8E8E8', success: '#2FA36B', warning: '#B7791F', danger: '#a84040', info: '#555555',
      heading: '#111111', body: '#111111', muted: '#707070', link: '#333333', code: '#222222',
      border: '#DDDDDD', onPrimary: '#FFFFFF',
      grad1: 'linear-gradient(135deg, #9a9a9a 0%, #555 100%)',
      grad2: 'radial-gradient(ellipse at top, #E0E0E0 0%, transparent 100%)',
      codeFont: CODE_FONT_DEFAULT,
    }),
  },
  cyberpunk: {
    label: 'Cyberpunk',
    desc: 'Neon green on black — matrix terminal',
    dark: preset({
      name: 'cyberpunk', light: false,
      bg: '#000a00', bg2: '#001a00', base: '#001200', raised: '#001000',
      primary: '#00ff41', secondary: '#002800', success: '#00ff41', warning: '#E3A008', danger: '#ff003c', info: '#00ff41',
      heading: '#00ff41', body: '#00ff41', muted: '#1a8a30', link: '#00ff41', code: '#00cc34',
      border: '#003000', onPrimary: '#000a00',
      grad1: 'linear-gradient(135deg, #00ff41 0%, #003a10 100%)',
      grad2: 'radial-gradient(ellipse at top, #00ff41 0%, transparent 100%)',
      codeFont: { family: '"Courier New", Courier, monospace', size: 13, ligatures: false },
      headerFont: { family: '"Courier New", Courier, monospace', weight: 700, tracking: '-0.02em' },
      bodyFont: { family: '"Courier New", Courier, monospace', weight: 400, size: 15, lineHeight: 1.55 },
    }),
    light: preset({
      name: 'cyberpunk', light: true,
      bg: '#F4FFF6', bg2: '#DFF5E4', base: '#FFFFFF', raised: '#FFFFFF',
      primary: '#008f2e', secondary: '#E0F4E5', success: '#008f2e', warning: '#B7791F', danger: '#ff003c', info: '#008f2e',
      heading: '#003d14', body: '#003d14', muted: '#3d7a52', link: '#008f2e', code: '#005c20',
      border: '#C6E8CF', onPrimary: '#FFFFFF',
      grad1: 'linear-gradient(135deg, #00b33a 0%, #006b22 100%)',
      grad2: 'radial-gradient(ellipse at top, #BDF2CC 0%, transparent 100%)',
      codeFont: { family: '"Courier New", Courier, monospace', size: 13, ligatures: false },
      headerFont: { family: '"Courier New", Courier, monospace', weight: 700, tracking: '-0.02em' },
      bodyFont: { family: '"Courier New", Courier, monospace', weight: 400, size: 15, lineHeight: 1.55 },
    }),
  },
  slate: {
    label: 'Slate',
    desc: 'Cool slate blue — focused developer theme',
    dark: preset({
      name: 'slate', light: false,
      bg: '#0d1117', bg2: '#21262d', base: '#161b22', raised: '#1c2128',
      primary: '#58a6ff', secondary: '#2a3038', success: '#55A583', warning: '#E3A008', danger: '#cf4848', info: '#58a6ff',
      heading: '#c9d1d9', body: '#c9d1d9', muted: '#8b949e', link: '#58a6ff', code: '#b7c7d6',
      border: '#30363d', onPrimary: '#0d1117',
      grad1: 'linear-gradient(135deg, #58a6ff 0%, #1f3a5f 100%)',
      grad2: 'radial-gradient(ellipse at top, #58a6ff 0%, transparent 100%)',
      codeFont: { family: '"JetBrains Mono", monospace', size: 13, ligatures: true },
    }),
    light: preset({
      name: 'slate', light: true,
      bg: '#F6F8FA', bg2: '#EAF0F6', base: '#FFFFFF', raised: '#FFFFFF',
      primary: '#0969da', secondary: '#EAF1F8', success: '#2FA36B', warning: '#B7791F', danger: '#cf222e', info: '#0969da',
      heading: '#1f2328', body: '#1f2328', muted: '#656d76', link: '#0969da', code: '#24292f',
      border: '#D8DEE4', onPrimary: '#FFFFFF',
      grad1: 'linear-gradient(135deg, #0969da 0%, #58a6ff 100%)',
      grad2: 'radial-gradient(ellipse at top, #C9E2FF 0%, transparent 100%)',
      codeFont: { family: '"JetBrains Mono", monospace', size: 13, ligatures: true },
    }),
  },
};

/* ---------- default custom blob (the pasted JSON) ---------- */
const THEME_DEFAULTS = {
  theme: 'nous',
  mode: 'light',
  tokens: {
    theme: 'nous',
    mode: 'light',
    gradient1: 'linear-gradient(135deg, #0053FD 0%, #8B7CFF 100%)',
    gradient2: 'radial-gradient(ellipse at top, #BBD4FF 0%, transparent 100%)',
    background1: '#F8FAFF',
    background2: '#F3F7FF',
    surface: { base: '#FFFFFF', raised: '#FFFFFF', overlay: 'rgba(255,255,255,0.72)' },
    function: {
      primary: '#0053FD',
      secondary: '#EAF1FE',
      success: '#2FA36B',
      warning: '#B7791F',
      danger: '#C72E4D',
      info: '#0053FD',
    },
    opacity: { subtle: 0.06, muted: 0.12, half: 0.5, strong: 0.72, solid: 1 },
    density: { scale: 1, unit: 4, controlHeight: 36, padding: 12 },
    edges: { radius: 4, borderWidth: 1, borderColor: 'rgba(15,23,42,0.14)' },
    highlights: {
      topEdge: 'rgba(255,255,255,0.85)',
      glow: 'rgba(0,83,253,0.22)',
      selection: 'rgba(0,83,253,0.18)',
    },
    elevation: {
      1: '0 1px 2px rgba(15,23,42,0.08)',
      2: '0 6px 16px rgba(15,23,42,0.10)',
      3: '0 24px 64px rgba(15,23,42,0.16)',
    },
    depth: { perspective: 1200, layerOffset: 8, innerShadow: 'inset 0 2px 8px rgba(15,23,42,0.08)' },
    gloss: { intensity: 0.18, angle: 115, sheen: 'rgba(255,255,255,0.9)', blend: 'overlay' },
    headerFont: { family: 'Inter Tight, sans-serif', weight: 650, tracking: '-0.02em' },
    bodyFont: { family: 'Inter, sans-serif', weight: 400, size: 15, lineHeight: 1.55 },
    codeFont: { family: 'JetBrains Mono, monospace', size: 13, ligatures: true },
    colorFont: { heading: '#17171A', body: '#17171A', muted: '#666678', link: '#0053FD', code: '#242432' },
    motion: { duration: 200, easing: 'cubic-bezier(0.2,0,0,1)' },
    blur: { backdrop: 18 },
    overrides: {},
  },
};

/* ---------- token editor schema ---------- */
const TOKEN_SCHEMA = [
  { label: 'Gradients', fields: [
    { path: 'gradient1', label: 'gradient1', type: 'gradient' },
    { path: 'gradient2', label: 'gradient2', type: 'gradient' },
  ]},
  { label: 'Backgrounds', fields: [
    { path: 'background1', label: 'background1', type: 'color' },
    { path: 'background2', label: 'background2', type: 'color' },
  ]},
  { label: 'Surface', fields: [
    { path: 'surface.base', label: 'base', type: 'color' },
    { path: 'surface.raised', label: 'raised', type: 'color' },
    { path: 'surface.overlay', label: 'overlay', type: 'color' },
  ]},
  { label: 'Function colors', fields: [
    { path: 'function.primary', label: 'primary', type: 'color' },
    { path: 'function.secondary', label: 'secondary', type: 'color' },
    { path: 'function.success', label: 'success', type: 'color' },
    { path: 'function.warning', label: 'warning', type: 'color' },
    { path: 'function.danger', label: 'danger', type: 'color' },
    { path: 'function.info', label: 'info', type: 'color' },
  ]},
  { label: 'Opacity', fields: [
    { path: 'opacity.subtle', label: 'subtle', type: 'slider', min: 0, max: 1, step: 0.01 },
    { path: 'opacity.muted', label: 'muted', type: 'slider', min: 0, max: 1, step: 0.01 },
    { path: 'opacity.half', label: 'half', type: 'slider', min: 0, max: 1, step: 0.01 },
    { path: 'opacity.strong', label: 'strong', type: 'slider', min: 0, max: 1, step: 0.01 },
    { path: 'opacity.solid', label: 'solid', type: 'slider', min: 0, max: 1, step: 0.01 },
  ]},
  { label: 'Density', fields: [
    { path: 'density.scale', label: 'scale', type: 'slider', min: 0.7, max: 1.4, step: 0.05 },
    { path: 'density.unit', label: 'unit', type: 'number', min: 2, max: 12 },
    { path: 'density.controlHeight', label: 'controlHeight', type: 'number', min: 24, max: 56 },
    { path: 'density.padding', label: 'padding', type: 'number', min: 4, max: 32 },
  ]},
  { label: 'Edges', fields: [
    { path: 'edges.radius', label: 'radius', type: 'slider', min: 0, max: 24, step: 1 },
    { path: 'edges.borderWidth', label: 'borderWidth', type: 'slider', min: 0, max: 4, step: 1 },
    { path: 'edges.borderColor', label: 'borderColor', type: 'color' },
  ]},
  { label: 'Highlights', fields: [
    { path: 'highlights.topEdge', label: 'topEdge', type: 'color' },
    { path: 'highlights.glow', label: 'glow', type: 'color' },
    { path: 'highlights.selection', label: 'selection', type: 'color' },
  ]},
  { label: 'Elevation (shadows)', fields: [
    { path: 'elevation.1', label: '1 — card', type: 'text' },
    { path: 'elevation.2', label: '2 — floating', type: 'text' },
    { path: 'elevation.3', label: '3 — modal', type: 'text' },
  ]},
  { label: 'Depth', fields: [
    { path: 'depth.perspective', label: 'perspective', type: 'number', min: 200, max: 4000, step: 100 },
    { path: 'depth.layerOffset', label: 'layerOffset', type: 'number', min: 0, max: 64 },
    { path: 'depth.innerShadow', label: 'innerShadow', type: 'text' },
  ]},
  { label: 'Gloss', fields: [
    { path: 'gloss.intensity', label: 'intensity', type: 'slider', min: 0, max: 1, step: 0.01 },
    { path: 'gloss.angle', label: 'angle', type: 'slider', min: 0, max: 360, step: 1 },
    { path: 'gloss.sheen', label: 'sheen', type: 'color' },
    { path: 'gloss.blend', label: 'blend', type: 'select', options: ['overlay', 'screen', 'soft-light', 'hard-light', 'plus-lighter', 'normal'] },
  ]},
  { label: 'Header font', fields: [
    { path: 'headerFont.family', label: 'family', type: 'text' },
    { path: 'headerFont.weight', label: 'weight', type: 'number', min: 100, max: 900, step: 50 },
    { path: 'headerFont.tracking', label: 'tracking', type: 'text' },
  ]},
  { label: 'Body font', fields: [
    { path: 'bodyFont.family', label: 'family', type: 'text' },
    { path: 'bodyFont.weight', label: 'weight', type: 'number', min: 100, max: 900, step: 50 },
    { path: 'bodyFont.size', label: 'size', type: 'number', min: 10, max: 22 },
    { path: 'bodyFont.lineHeight', label: 'lineHeight', type: 'number', min: 1, max: 2.2, step: 0.05 },
  ]},
  { label: 'Code font', fields: [
    { path: 'codeFont.family', label: 'family', type: 'text' },
    { path: 'codeFont.size', label: 'size', type: 'number', min: 8, max: 20 },
    { path: 'codeFont.ligatures', label: 'ligatures', type: 'checkbox' },
  ]},
  { label: 'Text colors', fields: [
    { path: 'colorFont.heading', label: 'heading', type: 'color' },
    { path: 'colorFont.body', label: 'body', type: 'color' },
    { path: 'colorFont.muted', label: 'muted', type: 'color' },
    { path: 'colorFont.link', label: 'link', type: 'color' },
    { path: 'colorFont.code', label: 'code', type: 'color' },
  ]},
  { label: 'Motion', fields: [
    { path: 'motion.duration', label: 'duration (ms)', type: 'number', min: 0, max: 2000, step: 10 },
    { path: 'motion.easing', label: 'easing', type: 'text' },
  ]},
  { label: 'Blur', fields: [
    { path: 'blur.backdrop', label: 'backdrop', type: 'number', min: 0, max: 60 },
  ]},
  { label: 'Overrides (raw CSS vars)', fields: [
    { path: 'overrides', label: 'overrides', type: 'json' },
  ]},
];

/* ---------- path helpers ---------- */
function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}
function setPath(obj, path, val) {
  const parts = path.split('.');
  let o = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (typeof o[parts[i]] !== 'object' || o[parts[i]] === null) o[parts[i]] = {};
    o = o[parts[i]];
  }
  o[parts[parts.length - 1]] = val;
}
function deepClone(o) { return JSON.parse(JSON.stringify(o)); }

/* ---------- apply blob → CSS custom properties ---------- */
function applyUiTokens(tokens, theme, mode) {
  const root = document.documentElement;
  const t = tokens || {};
  const m = mode || t.mode || 'dark';
  const set = (p, v) => {
    if (v !== undefined && v !== null) root.style.setProperty(p, String(v));
  };
  set('--t-theme', theme || t.theme || 'custom');
  set('--t-mode', m);
  set('--t-scheme', m);
  set('--t-on-primary', t.onPrimary || '#FFFFFF');
  set('--t-gradient1', t.gradient1);
  set('--t-gradient2', t.gradient2);
  set('--t-background1', t.background1);
  set('--t-background2', t.background2);
  const g = (grp) => t[grp] || {};
  const s = g('surface'); set('--t-surface-base', s.base); set('--t-surface-raised', s.raised); set('--t-surface-overlay', s.overlay);
  const f = g('function'); set('--t-function-primary', f.primary); set('--t-function-secondary', f.secondary); set('--t-function-success', f.success); set('--t-function-warning', f.warning); set('--t-function-danger', f.danger); set('--t-function-info', f.info);
  const o = g('opacity'); set('--t-opacity-subtle', o.subtle); set('--t-opacity-muted', o.muted); set('--t-opacity-half', o.half); set('--t-opacity-strong', o.strong); set('--t-opacity-solid', o.solid);
  const d = g('density'); set('--t-density-scale', d.scale); set('--t-density-unit', d.unit); set('--t-density-controlHeight', d.controlHeight); set('--t-density-padding', d.padding);
  const e = g('edges'); set('--t-edges-radius', e.radius); set('--t-edges-borderWidth', e.borderWidth); set('--t-edges-borderColor', e.borderColor);
  const h = g('highlights'); set('--t-highlights-topEdge', h.topEdge); set('--t-highlights-glow', h.glow); set('--t-highlights-selection', h.selection);
  const el = g('elevation'); set('--t-elevation-1', el['1']); set('--t-elevation-2', el['2']); set('--t-elevation-3', el['3']);
  const dp = g('depth'); set('--t-depth-perspective', dp.perspective); set('--t-depth-layerOffset', dp.layerOffset); set('--t-depth-innerShadow', dp.innerShadow);
  const gl = g('gloss'); set('--t-gloss-intensity', gl.intensity); set('--t-gloss-angle', gl.angle); set('--t-gloss-sheen', gl.sheen); set('--t-gloss-blend', gl.blend);
  const hf = g('headerFont'); set('--t-headerFont-family', hf.family); set('--t-headerFont-weight', hf.weight); set('--t-headerFont-tracking', hf.tracking);
  const bf = g('bodyFont'); set('--t-bodyFont-family', bf.family); set('--t-bodyFont-weight', bf.weight); set('--t-bodyFont-size', bf.size); set('--t-bodyFont-lineHeight', bf.lineHeight);
  const cf = g('codeFont'); set('--t-codeFont-family', cf.family); set('--t-codeFont-size', cf.size); set('--t-codeFont-ligatures', cf.ligatures ? 1 : 0);
  const tf = g('colorFont'); set('--t-color-heading', tf.heading); set('--t-color-body', tf.body); set('--t-color-muted', tf.muted); set('--t-color-link', tf.link); set('--t-color-code', tf.code);
  const mo = g('motion'); set('--t-motion-duration', mo.duration); set('--t-motion-easing', mo.easing);
  const bl = g('blur'); set('--t-blur-backdrop', bl.backdrop);
  root.dataset.theme = theme || t.theme || 'custom';
  root.dataset.mode = m;
  document.documentElement.style.colorScheme = m;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta && t.background1) meta.content = t.background1;
  if (t.overrides && typeof t.overrides === 'object') {
    for (const k in t.overrides) root.style.setProperty(k, String(t.overrides[k]));
  }
}

/* ---------- resolve the blob that should drive the UI ---------- */
function resolveUiBlob(cfg) {
  // cfg = { theme, mode, tokens }
  const theme = cfg.theme || 'custom';
  const mode = cfg.mode || 'dark';
  if (theme !== 'custom' && THEME_PRESETS[theme]) {
    const p = THEME_PRESETS[theme][mode] || THEME_PRESETS[theme].dark;
    return { blob: p, theme, mode, fromPreset: true };
  }
  // custom: deep-merge stored tokens over defaults so missing keys never break.
  const merged = deepClone(THEME_DEFAULTS.tokens);
  const src = cfg.tokens || {};
  for (const k in src) merged[k] = typeof src[k] === 'object' && src[k] !== null && !Array.isArray(src[k])
    ? Object.assign({}, merged[k], src[k])
    : src[k];
  merged.theme = 'custom';
  merged.mode = mode;
  return { blob: merged, theme: 'custom', mode, fromPreset: false };
}
