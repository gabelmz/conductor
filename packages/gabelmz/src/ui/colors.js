/**
 * ANSI Color & Styling Utility for gabelmz CLI
 * Supports 24-bit TrueColor, 256-color fallbacks, and fire gradients
 */

const isColorSupported = !process.env.NO_COLOR && (process.stdout.isTTY || process.env.FORCE_COLOR);

// Basic styles
export const reset = isColorSupported ? '\x1b[0m' : '';
export const bold = (s) => (isColorSupported ? `\x1b[1m${s}\x1b[22m` : s);
export const dim = (s) => (isColorSupported ? `\x1b[2m${s}\x1b[22m` : s);
export const italic = (s) => (isColorSupported ? `\x1b[3m${s}\x1b[23m` : s);
export const underline = (s) => (isColorSupported ? `\x1b[4m${s}\x1b[24m` : s);
export const inverse = (s) => (isColorSupported ? `\x1b[7m${s}\x1b[27m` : s);

// Backgrounds
export const bgBlack = (s) => (isColorSupported ? `\x1b[40m${s}\x1b[49m` : s);
export const bgDark = (s) => (isColorSupported ? `\x1b[48;2;10;10;12m${s}\x1b[49m` : s);
export const bgRed = (s) => (isColorSupported ? `\x1b[41m${s}\x1b[49m` : s);
export const bgOrange = (s) => (isColorSupported ? `\x1b[48;2;180;60;0m${s}\x1b[49m` : s);

// Standard colors
export const red = (s) => (isColorSupported ? `\x1b[31m${s}\x1b[39m` : s);
export const green = (s) => (isColorSupported ? `\x1b[32m${s}\x1b[39m` : s);
export const yellow = (s) => (isColorSupported ? `\x1b[33m${s}\x1b[39m` : s);
export const blue = (s) => (isColorSupported ? `\x1b[34m${s}\x1b[39m` : s);
export const magenta = (s) => (isColorSupported ? `\x1b[35m${s}\x1b[39m` : s);
export const cyan = (s) => (isColorSupported ? `\x1b[36m${s}\x1b[39m` : s);
export const white = (s) => (isColorSupported ? `\x1b[37m${s}\x1b[39m` : s);
export const gray = (s) => (isColorSupported ? `\x1b[90m${s}\x1b[39m` : s);

// TrueColor RGB builder
export const rgb = (r, g, b) => (s) => (isColorSupported ? `\x1b[38;2;${r};${g};${b}m${s}\x1b[39m` : s);
export const bgRgb = (r, g, b) => (s) => (isColorSupported ? `\x1b[48;2;${r};${g};${b}m${s}\x1b[49m` : s);

// Fire & Ember Palette
export const fireCrimson = rgb(255, 30, 30);
export const fireRed = rgb(255, 68, 0);
export const fireOrange = rgb(255, 128, 0);
export const fireAmber = rgb(255, 180, 0);
export const fireYellow = rgb(255, 230, 60);
export const fireWhite = rgb(255, 255, 210);
export const skullBone = rgb(225, 230, 245);
export const skullShadow = rgb(110, 118, 140);
export const eyeGlow = rgb(255, 45, 0);
export const eyePupil = rgb(255, 240, 50);
export const cyanGlow = rgb(0, 240, 255);

// Linear RGB interpolation
function lerpColor(c1, c2, factor) {
  return [
    Math.round(c1[0] + factor * (c2[0] - c1[0])),
    Math.round(c1[1] + factor * (c2[1] - c1[1])),
    Math.round(c1[2] + factor * (c2[2] - c1[2])),
  ];
}

// Flame gradient applier across a string
export function flameGradient(text) {
  if (!isColorSupported || !text) return text;
  const stops = [
    [255, 240, 100], // Yellow
    [255, 140, 0],   // Orange
    [255, 50, 0],    // Red-Orange
    [200, 10, 30],   // Crimson
    [120, 0, 40],    // Deep ember
  ];

  const chars = [...text];
  const len = chars.length;
  if (len <= 1) return fireYellow(text);

  return chars
    .map((ch, i) => {
      if (ch === ' ' || ch === '\n') return ch;
      const progress = i / (len - 1);
      const segment = progress * (stops.length - 1);
      const idx = Math.min(Math.floor(segment), stops.length - 2);
      const factor = segment - idx;
      const [r, g, b] = lerpColor(stops[idx], stops[idx + 1], factor);
      return `\x1b[38;2;${r};${g};${b}m${ch}\x1b[39m`;
    })
    .join('');
}

// Vertical flame gradient for multiline text
export function verticalFlame(lines) {
  if (!isColorSupported) return lines.join('\n');
  const stops = [
    [255, 245, 120], // Flame top (yellow)
    [255, 160, 0],   // Bright orange
    [255, 60, 0],    // Fiery red
    [210, 15, 30],   // Crimson
    [160, 165, 180], // Skull bone
    [230, 235, 245], // Skull highlight
  ];

  const total = lines.length;
  return lines
    .map((line, row) => {
      const progress = row / Math.max(1, total - 1);
      const segment = progress * (stops.length - 1);
      const idx = Math.min(Math.floor(segment), stops.length - 2);
      const factor = segment - idx;
      const [r, g, b] = lerpColor(stops[idx], stops[idx + 1], factor);
      return `\x1b[38;2;${r};${g};${b}m${line}\x1b[39m`;
    })
    .join('\n');
}

// Box component
export function box(content, options = {}) {
  const {
    title = '',
    borderColor = fireOrange,
    padding = 1,
    minWidth = 50,
  } = options;

  const rawLines = Array.isArray(content) ? content : String(content).split('\n');
  const stripAnsi = (str) => str.replace(/\x1b\[[0-9;]*m/g, '');
  const contentWidth = Math.max(
    minWidth,
    stripAnsi(title).length + 4,
    ...rawLines.map((l) => stripAnsi(l).length)
  );

  const padStr = ' '.repeat(padding);
  const width = contentWidth + padding * 2;

  const topBorder = title
    ? borderColor(`┌─ `) + bold(title) + borderColor(` ${'─'.repeat(Math.max(0, width - stripAnsi(title).length - 4))}┐`)
    : borderColor(`┌${'─'.repeat(width)}┐`);

  const bottomBorder = borderColor(`└${'─'.repeat(width)}┘`);

  const formattedLines = rawLines.map((line) => {
    const visibleLen = stripAnsi(line).length;
    const rightPad = ' '.repeat(Math.max(0, contentWidth - visibleLen));
    return borderColor('│') + padStr + line + rightPad + padStr + borderColor('│');
  });

  return [topBorder, ...formattedLines, bottomBorder].join('\n');
}

// Badge helper
export function badge(label, color = fireOrange) {
  return color(`[${label}]`);
}
