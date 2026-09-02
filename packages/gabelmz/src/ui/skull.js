/**
 * Flaming Eye Skull ASCII / ANSI Visual Engine
 * Deep black background with blazing fire gradients and glowing fiery eyes
 */

import {
  bold,
  dim,
  reset,
  fireCrimson,
  fireRed,
  fireOrange,
  fireAmber,
  fireYellow,
  fireWhite,
  skullBone,
  skullShadow,
  eyeGlow,
  eyePupil,
  bgBlack,
  bgDark,
  cyanGlow,
  flameGradient,
} from './colors.js';

// The Flaming Eye Skull ASCII Artwork (segmented by features for precision coloring)
export function renderFlamingSkull({ animated = false, eyeColor = 'fire' } = {}) {
  const isEyeFire = eyeColor === 'fire';
  const pupil = isEyeFire ? eyePupil('◉') : cyanGlow('◉');
  const eyeHalo = isEyeFire ? eyeGlow('✦') : cyanGlow('✦');
  const eyeL = `${eyeHalo}${pupil}${eyeHalo}`;
  const eyeR = `${eyeHalo}${pupil}${eyeHalo}`;

  const flame1 = (s) => fireYellow(bold(s));
  const flame2 = (s) => fireAmber(bold(s));
  const flame3 = (s) => fireOrange(bold(s));
  const flame4 = (s) => fireRed(bold(s));
  const flame5 = (s) => fireCrimson(bold(s));
  const bone = (s) => skullBone(bold(s));
  const shadow = (s) => skullShadow(s);

  const lines = [
    // Top leaping flames
    `       ${flame1('(')}  ${flame2('.')}  ${flame1(')')}              ${flame1('(')}  ${flame2('.')}  ${flame1(')')}`,
    `      ${flame2(') \\')} ${flame1('|')} ${flame2('/ (')}    ${flame1('/\\')}      ${flame2(') \\')} ${flame1('|')} ${flame2('/ (')}`,
    `     ${flame3('(  / \\  )')}  ${flame2('/  \\')}   ${flame3('(  / \\  )')}`,
    `    ${flame3(') \\')} ${flame2('| |')} ${flame3('/ (')}  ${flame2('( () )')}  ${flame3(') \\')} ${flame2('| |')} ${flame3('/ (')}`,
    `   ${flame4('(   \\_/   )')}  ${flame3('\\__/')}  ${flame4('(   \\_/   )')}`,
    `  ${flame4('/ \\')} ${flame3('(')} ${bone('_______')} ${flame3(')')}        ${flame3('(')} ${bone('_______')} ${flame3(')')} ${flame4('/ \\')}`,
    ` ${flame5('(   ')} ${bone('/       \\')}  ${flame4(')    (')}  ${bone('/       \\')} ${flame5('   )')}`,
    `${flame5('  \\_')} ${bone('/    ___  \\')} ${flame4('/      \\')} ${bone('/  ___    \\')} ${flame5('_/')}`,
    `    ${bone('|   /   \\  |')}${flame4('/        \\')}${bone('|  /   \\   |')}`,
    `    ${bone('|  |')} ${eyeL} ${bone('| |')}  ${flame4('()  ()')}  ${bone('| |')} ${eyeR} ${bone('|  |')}`,
    `    ${bone('|   \\___/  |')}${flame5('\\        /')}${bone('|  \\___/   |')}`,
    `    ${bone('\\_       _/')}  ${flame4(')____(')}  ${bone('\\_       _/')}`,
    `      ${bone('|     |')}    ${flame3('/ \\  / \\')}    ${bone('|     |')}`,
    `      ${bone('|  ▲  |')}   ${flame4('(   \\/   )')}   ${bone('|  ▲  |')}`,
    `      ${bone('\\     /')}    ${flame5('\\______/')}    ${bone('\\     /')}`,
    `       ${bone('\\   /')}   ${bone('[][][][][][]')}   ${bone('\\   /')}`,
    `        ${bone('| |')}    ${bone('| || || || |')}    ${bone('| |')}`,
    `        ${bone('| |')}    ${bone('|_||_||_||_|')}    ${bone('| |')}`,
    `        ${bone('\\_/')}      ${bone('\\______/')}      ${bone('\\_/')}`,
    `           ${flame5('\\_')}    ${flame4('~~~~~~')}    ${flame5('_/')}`,
    `             ${flame4(')__')}  ${flame3('~~~~')}  ${flame4('__(')}`,
    `                ${flame5('\\_')}${flame4('~~~~')}${flame5('_/')}`,
  ];

  return lines.map((l) => bgBlack(l)).join('\n');
}

// Full Header Banner with Skull and Title
export function printSkullBanner({ subline = '', version = '1.0.0' } = {}) {
  const skullArt = renderFlamingSkull();
  const titleText = flameGradient('   ██████╗  █████╗ ██████╗ ███████╗██╗     ███╗   ███╗███████╗');
  const titleText2 = flameGradient('  ██╔════╝ ██╔══██╗██╔══██╗██╔════╝██║     ████╗ ████║╚══███╔╝');
  const titleText3 = flameGradient('  ██║  ███╗███████║██████╔╝█████╗  ██║     ██╔████╔██║  ███╔╝ ');
  const titleText4 = flameGradient('  ██║   ██║██╔══██║██╔══██╗██╔══╝  ██║     ██║╚██╔╝██║ ███╔╝  ');
  const titleText5 = flameGradient('  ╚██████╔╝██║  ██║██████╔╝███████╗███████╗██║ ╚═╝ ██║███████╗');
  const titleText6 = flameGradient('   ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚══════╝╚══════╝╚═╝     ╚═╝╚══════╝');

  console.log(bgBlack('\n' + skullArt));
  console.log(bgBlack(''));
  console.log(bgBlack(titleText));
  console.log(bgBlack(titleText2));
  console.log(bgBlack(titleText3));
  console.log(bgBlack(titleText4));
  console.log(bgBlack(titleText5));
  console.log(bgBlack(titleText6));
  console.log(bgBlack(''));
  console.log(
    bgBlack(
      `   ${fireAmber('🔥')} ${bold(fireWhite('gabelmz CLI'))} ${dim(skullBone(`v${version}`))}  ${dim('•')}  ${fireRed('Dark Terminal Engine')}  ${dim('•')}  ${skullBone('Obsidian / AI / NPM')}`
    )
  );
  if (subline) {
    console.log(bgBlack(`   ${dim(subline)}`));
  }
  console.log(bgBlack(''));
}

// Compact Banner for subcommands
export function printCompactBanner(title = '') {
  const miniSkull = `${fireRed('💀')} ${bold(fireYellow('gabelmz'))}`;
  const sep = dim(fireOrange(' ─── '));
  const tag = title ? bold(fireWhite(title)) : '';
  console.log(bgBlack(`\n ${miniSkull}${sep}${tag}\n`));
}

// Flame animation loop (for showcase / idle TUI)
export async function animateFlames(durationMs = 2500) {
  if (!process.stdout.isTTY) {
    printSkullBanner();
    return;
  }

  const frames = [
    { eye: 'fire', shift: 0 },
    { eye: 'cyan', shift: 1 },
    { eye: 'fire', shift: 2 },
    { eye: 'cyan', shift: 1 },
  ];

  const startTime = Date.now();
  let frameIdx = 0;

  // Hide cursor
  process.stdout.write('\x1b[?25l');

  try {
    while (Date.now() - startTime < durationMs) {
      const { eye } = frames[frameIdx % frames.length];
      console.clear();
      console.log(renderFlamingSkull({ eyeColor: eye }));
      console.log(
        bgBlack(
          `\n        ${fireYellow('⚡')} ${bold(fireWhite('F L A M I N G   E Y E   S K U L L'))} ${fireYellow('⚡')}\n`
        )
      );
      frameIdx++;
      await new Promise((r) => setTimeout(r, 180));
    }
  } finally {
    // Show cursor
    process.stdout.write('\x1b[?25h');
  }
}
