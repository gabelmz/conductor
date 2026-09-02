/**
 * Custom Terminal UI (TUI) with Deep Black Background & Flaming Eye Skull
 * Interactive menu, status indicators, and keyboard-driven navigation
 */

import { createInterface, emitKeypressEvents } from 'node:readline';
import { getNpmUser } from './npm.js';
import { discoverVaults } from './vaults.js';
import { getOpenRouterKey, getVaultsDir, loadConfig } from '../config.js';
import {
  bold,
  dim,
  fireAmber,
  fireCrimson,
  fireOrange,
  fireRed,
  fireWhite,
  fireYellow,
  gray,
  green,
  cyan,
  badge,
  box,
  bgBlack,
  flameGradient,
} from '../ui/colors.js';
import { printSkullBanner, renderFlamingSkull, animateFlames } from '../ui/skull.js';
import { runVaultCommand } from './vaults.js';
import { runChatCommand } from './chat.js';
import { runNpmCommand } from './npm.js';
import { runConfigCommand } from './config.js';

const MENU_ITEMS = [
  {
    id: 'vaults',
    label: 'Search Obsidian Vaults',
    icon: '🔍',
    desc: 'Full-text markdown search, frontmatter tags & note links',
  },
  {
    id: 'chat',
    label: 'OpenRouter AI Free Chat',
    icon: '💬',
    desc: 'Llama 3.3, Gemini 2.0, DeepSeek R1 scaffold (no key required)',
  },
  {
    id: 'npm',
    label: 'NPM Toolkit & Pre-Publish Check',
    icon: '📦',
    desc: 'Verify auth, test package.json, dry-run publish & inspect scripts',
  },
  {
    id: 'flame',
    label: 'Flaming Eye Skull Animation',
    icon: '🔥',
    desc: 'Live pulsing flame and eye glow effect showcase',
  },
  {
    id: 'config',
    label: 'Settings & API Keys',
    icon: '⚙️ ',
    desc: 'Configure vaults folder, default AI models & preferences',
  },
  {
    id: 'exit',
    label: 'Exit Terminal',
    icon: '🚪',
    desc: 'Quit gabelmz CLI',
  },
];

function renderMenu(selectedIndex, npmUser, vaultsCount, hasAiKey) {
  console.clear();
  printSkullBanner({ version: '1.0.0' });

  // Status Pills
  const npmStatus = npmUser.ok ? green(`npm: @${npmUser.user}`) : fireRed('npm: offline');
  const vaultStatus = cyan(`vaults: ${vaultsCount} detected`);
  const aiStatus = hasAiKey ? green('openrouter: key set') : fireAmber('openrouter: scaffold mode');

  console.log(
    bgBlack(
      `   ${fireAmber('●')} ${npmStatus}   ${fireAmber('●')} ${vaultStatus}   ${fireAmber('●')} ${aiStatus}\n`
    )
  );

  console.log(bgBlack(`   ${bold(fireOrange('Select an action (use ↑/↓ arrows or 1-6, Enter to launch):'))}\n`));

  MENU_ITEMS.forEach((item, idx) => {
    const isSelected = idx === selectedIndex;
    const num = `${idx + 1}.`;
    if (isSelected) {
      const line = `  ${fireYellow('➔')} ${bold(fireWhite(`[ ${item.icon} ${item.label} ]`))}  ${fireYellow(`— ${item.desc}`)}`;
      console.log(bgBlack(line));
    } else {
      const line = `    ${dim(num)} ${item.icon} ${fireOrange(item.label)}  ${dim(`— ${item.desc}`)}`;
      console.log(bgBlack(line));
    }
  });

  console.log(bgBlack(`\n   ${dim('Press Q or Ctrl+C to exit.')}\n`));
}

export async function runInteractiveTui() {
  const vaultsDir = getVaultsDir();
  const vaults = discoverVaults(vaultsDir);
  const npmUser = getNpmUser();
  const hasAiKey = Boolean(getOpenRouterKey());

  let selectedIndex = 0;

  if (!process.stdin.isTTY) {
    // Non-interactive fallback
    printSkullBanner();
    console.log(bgBlack(`Run with subcommands:`));
    console.log(bgBlack(`  gabelmz vault <query>`));
    console.log(bgBlack(`  gabelmz chat`));
    console.log(bgBlack(`  gabelmz npm check`));
    return 0;
  }

  // Interactive Keypress loop
  emitKeypressEvents(process.stdin);
  if (process.stdin.setRawMode) {
    process.stdin.setRawMode(true);
  }
  process.stdin.resume();

  renderMenu(selectedIndex, npmUser, vaults.length, hasAiKey);

  return new Promise((resolve) => {
    async function onKeypress(str, key) {
      if (key.ctrl && key.name === 'c') {
        cleanup();
        process.exit(0);
      }

      if (key.name === 'up' || key.name === 'k') {
        selectedIndex = (selectedIndex - 1 + MENU_ITEMS.length) % MENU_ITEMS.length;
        renderMenu(selectedIndex, npmUser, vaults.length, hasAiKey);
        return;
      }

      if (key.name === 'down' || key.name === 'j') {
        selectedIndex = (selectedIndex + 1) % MENU_ITEMS.length;
        renderMenu(selectedIndex, npmUser, vaults.length, hasAiKey);
        return;
      }

      // Numeric keys 1-6
      const num = parseInt(str, 10);
      if (num >= 1 && num <= MENU_ITEMS.length) {
        selectedIndex = num - 1;
        renderMenu(selectedIndex, npmUser, vaults.length, hasAiKey);
        await executeItem(MENU_ITEMS[selectedIndex].id);
        return;
      }

      if (key.name === 'q' || key.name === 'escape') {
        cleanup();
        console.log(bgBlack(`\n   ${fireYellow('⚡')} ${bold(fireWhite('Keep on burning!'))}\n`));
        resolve(0);
        return;
      }

      if (key.name === 'return' || key.name === 'enter' || key.name === 'space') {
        await executeItem(MENU_ITEMS[selectedIndex].id);
      }
    }

    async function executeItem(id) {
      cleanup();

      if (id === 'exit') {
        console.log(bgBlack(`\n   ${fireYellow('⚡')} ${bold(fireWhite('Keep on burning!'))}\n`));
        resolve(0);
        return;
      }

      if (id === 'flame') {
        await animateFlames(3000);
      } else if (id === 'vaults') {
        await runVaultCommand([]);
      } else if (id === 'chat') {
        await runChatCommand([]);
      } else if (id === 'npm') {
        await runNpmCommand(['check']);
      } else if (id === 'config') {
        await runConfigCommand([]);
      }

      // Re-arm interactive TUI
      if (process.stdin.setRawMode) {
        process.stdin.setRawMode(true);
      }
      process.stdin.resume();
      process.stdin.on('keypress', onKeypress);
      renderMenu(selectedIndex, npmUser, vaults.length, Boolean(getOpenRouterKey()));
    }

    function cleanup() {
      process.stdin.removeListener('keypress', onKeypress);
      if (process.stdin.setRawMode) {
        process.stdin.setRawMode(false);
      }
      process.stdin.pause();
    }

    process.stdin.on('keypress', onKeypress);
  });
}
