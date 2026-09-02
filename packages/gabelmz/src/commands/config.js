/**
 * Config CLI command handler for ~/.gabelmz/config.json
 */

import { getConfigPath, loadConfig, saveConfig } from '../config.js';
import {
  bold,
  dim,
  fireAmber,
  fireOrange,
  fireRed,
  fireWhite,
  fireYellow,
  green,
  cyan,
} from '../ui/colors.js';
import { printCompactBanner } from '../ui/skull.js';

export async function runConfigCommand(args = []) {
  printCompactBanner('Configuration Manager');

  const action = args[0] || 'list';
  const key = args[1];
  const val = args.slice(2).join(' ');

  const cfg = loadConfig();

  if (action === 'get') {
    if (!key) {
      console.log(`\n ${fireRed('Usage:')} gabelmz config get <key>\n`);
      return 1;
    }
    const valFound = cfg[key];
    if (valFound === undefined) {
      console.log(`\n ${dim(`Key "${key}" is not set.`)}\n`);
    } else {
      console.log(`\n  ${cyan(key)} = ${bold(fireYellow(String(valFound)))}\n`);
    }
    return 0;
  }

  if (action === 'set') {
    if (!key || val === undefined || val === '') {
      console.log(`\n ${fireRed('Usage:')} gabelmz config set <key> <value>\n`);
      return 1;
    }
    saveConfig({ [key]: val });
    console.log(`\n  ${green('✓')} Set ${cyan(key)} = ${bold(fireYellow(val))}\n`);
    return 0;
  }

  if (action === 'path') {
    console.log(`\n  ${dim('Config file:')} ${cyan(getConfigPath())}\n`);
    return 0;
  }

  // List all config
  console.log(`\n${bold(fireOrange('Active Configuration:'))} ${dim(`(${getConfigPath()})`)}\n`);
  for (const [k, v] of Object.entries(cfg)) {
    const displayVal = k.includes('key') && v ? `${String(v).slice(0, 8)}...${String(v).slice(-4)} (hidden)` : String(v);
    console.log(`  ${fireAmber('•')} ${cyan(k.padEnd(22))} = ${bold(fireWhite(displayVal))}`);
  }
  console.log(`\n ${dim('Set any value with:')} ${fireYellow('gabelmz config set <key> <value>')}\n`);
  return 0;
}
