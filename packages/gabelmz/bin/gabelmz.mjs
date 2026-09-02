#!/usr/bin/env node
/**
 * gabelmz CLI - Developer Toolkit
 *
 * Usage:
 *   gabelmz                           Launch interactive TUI dashboard with flaming skull
 *   gabelmz vault <query>             Search across Obsidian vaults
 *   gabelmz chat [prompt]             OpenRouter free AI chat (scaffold ready)
 *   gabelmz npm <check|publish|bump>  NPM wrapper & pre-publish health checker
 *   gabelmz config <get|set|list>     Manage settings and API keys
 *   gabelmz skull                     Display the flaming eye skull artwork
 */

import { runVaultCommand } from '../src/commands/vaults.js';
import { runChatCommand } from '../src/commands/chat.js';
import { runNpmCommand } from '../src/commands/npm.js';
import { runConfigCommand } from '../src/commands/config.js';
import { runInteractiveTui } from '../src/commands/tui.js';
import { printSkullBanner, animateFlames } from '../src/ui/skull.js';
import { bold, dim, fireAmber, fireOrange, fireRed, fireWhite, fireYellow, cyan, green } from '../src/ui/colors.js';

const VERSION = '1.0.0';

async function main() {
  const args = process.argv.slice(2);
  const cmd = args[0]?.toLowerCase();
  const rest = args.slice(1);

  if (!cmd) {
    // Default: interactive TUI
    await runInteractiveTui();
    return;
  }

  switch (cmd) {
    case 'vault':
    case 'vaults':
    case 'search':
    case 'obsidian':
      process.exit(await runVaultCommand(rest));
      break;

    case 'chat':
    case 'ai':
    case 'openrouter':
      process.exit(await runChatCommand(rest));
      break;

    case 'npm':
    case 'pkg':
    case 'publish':
      process.exit(await runNpmCommand(cmd === 'publish' ? ['publish', ...rest] : rest));
      break;

    case 'config':
    case 'settings':
    case 'cfg':
      process.exit(await runConfigCommand(rest));
      break;

    case 'skull':
    case 'flame':
    case 'banner':
      if (rest[0] === 'animate' || rest[0] === '-a') {
        await animateFlames(4000);
      } else {
        printSkullBanner({ version: VERSION });
      }
      process.exit(0);
      break;

    case 'tui':
    case 'menu':
    case 'dashboard':
      await runInteractiveTui();
      break;

    case '--version':
    case '-v':
    case 'version':
      console.log(`gabelmz v${VERSION}`);
      process.exit(0);
      break;

    case '--help':
    case '-h':
    case 'help':
    default:
      printSkullBanner({ version: VERSION });
      console.log(` ${bold(fireOrange('COMMANDS:'))}`);
      console.log(`   ${bold(fireYellow('gabelmz'))}                               Launch interactive dark TUI with flaming skull`);
      console.log(`   ${bold(fireYellow('gabelmz vault <query>'))}                 Search Obsidian vaults for markdown notes`);
      console.log(`   ${bold(fireYellow('gabelmz vault --tag <tag>'))}             Search Obsidian notes by tag`);
      console.log(`   ${bold(fireYellow('gabelmz vault list'))}                    List all detected Obsidian vaults`);
      console.log(`   ${bold(fireYellow('gabelmz chat [prompt]'))}                 OpenRouter free AI chat (scaffold mode / streaming)`);
      console.log(`   ${bold(fireYellow('gabelmz npm check'))}                     Pre-publish health check (package.json + dry-run)`);
      console.log(`   ${bold(fireYellow('gabelmz npm publish'))}                   Safely publish current package to npm`);
      console.log(`   ${bold(fireYellow('gabelmz npm bump <patch|minor>'))}        Bump semantic version in package.json`);
      console.log(`   ${bold(fireYellow('gabelmz npm whoami'))}                    Check npm logged in account & registry`);
      console.log(`   ${bold(fireYellow('gabelmz config list'))}                   View all saved settings`);
      console.log(`   ${bold(fireYellow('gabelmz config set <key> <val>'))}        Update config (e.g. openrouter_key, vaults_dir)`);
      console.log(`   ${bold(fireYellow('gabelmz skull [animate]'))}               Render flaming eye skull artwork\n`);
      process.exit(cmd === 'help' || cmd === '--help' || cmd === '-h' ? 0 : 1);
  }
}

main().catch((err) => {
  console.error(`\n${fireRed('Fatal error:')} ${err.message}\n`);
  process.exit(1);
});
