/**
 * Obsidian Vaults Search Engine
 * Scans, parses, and searches Markdown files across Obsidian vaults
 */

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, basename, extname } from 'node:path';
import { getVaultsDir, loadConfig } from '../config.js';
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
} from '../ui/colors.js';
import { printCompactBanner } from '../ui/skull.js';

// Discover all Obsidian vaults inside root vaults directory
export function discoverVaults(vaultsDir = getVaultsDir()) {
  if (!existsSync(vaultsDir)) {
    return [];
  }
  const entries = readdirSync(vaultsDir, { withFileTypes: true });
  const vaults = [];

  for (const entry of entries) {
    if (entry.isDirectory()) {
      const fullPath = join(vaultsDir, entry.name);
      if (entry.name.startsWith('.') || entry.name.startsWith('_')) continue;
      if (entry.name === 'node_modules' || entry.name === 'dist' || entry.name === '.venv') continue;

      // Check if it's an obsidian vault or contains markdown
      const hasObsidian = existsSync(join(fullPath, '.obsidian'));
      const hasMd = hasMarkdownFiles(fullPath, 2);
      if (hasObsidian || hasMd) {
        vaults.push({
          name: entry.name,
          path: fullPath,
          hasObsidianConfig: hasObsidian,
        });
      }
    }
  }
  return vaults;
}

function hasMarkdownFiles(dir, maxDepth = 2, currentDepth = 0) {
  if (currentDepth > maxDepth || !existsSync(dir)) return false;
  try {
    const files = readdirSync(dir, { withFileTypes: true });
    for (const f of files) {
      if (f.name.startsWith('.') || f.name === 'node_modules') continue;
      if (f.isFile() && (f.name.endsWith('.md') || f.name.endsWith('.markdown'))) return true;
      if (f.isDirectory() && hasMarkdownFiles(join(dir, f.name), maxDepth, currentDepth + 1)) return true;
    }
  } catch {
    return false;
  }
  return false;
}

// Recursively find all markdown files in a directory
function collectMarkdownFiles(dir, baseDir = dir) {
  const mdFiles = [];
  if (!existsSync(dir)) return mdFiles;

  const stack = [dir];
  while (stack.length > 0) {
    const current = stack.pop();
    let entries = [];
    try {
      entries = readdirSync(current, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const entry of entries) {
      const fullPath = join(current, entry.name);
      const name = entry.name;
      if (name.startsWith('.') || name === 'node_modules' || name === '.git' || name === '.venv') {
        continue;
      }
      if (entry.isDirectory()) {
        stack.push(fullPath);
      } else if (entry.isFile() && (name.endsWith('.md') || name.endsWith('.markdown'))) {
        mdFiles.push({
          fullPath,
          relPath: relative(baseDir, fullPath),
          fileName: name,
        });
      }
    }
  }
  return mdFiles;
}

// Extract YAML Frontmatter metadata
function parseFrontmatter(content) {
  const result = { tags: [], title: '', properties: {} };
  const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!fmMatch) return { frontmatter: result, body: content };

  const rawYaml = fmMatch[1];
  const lines = rawYaml.split(/\r?\n/);
  for (const line of lines) {
    const match = line.match(/^([a-zA-Z0-9_-]+):\s*(.*)$/);
    if (match) {
      const [, key, val] = match;
      const cleanVal = val.trim().replace(/^['"]|['"]$/g, '');
      result.properties[key] = cleanVal;
      if (key.toLowerCase() === 'title') result.title = cleanVal;
      if (key.toLowerCase() === 'tags' || key.toLowerCase() === 'tag') {
        if (cleanVal.startsWith('[') && cleanVal.endsWith(']')) {
          result.tags = cleanVal.slice(1, -1).split(',').map((t) => t.trim().replace(/^[#]/, '')).filter(Boolean);
        } else if (cleanVal) {
          result.tags.push(cleanVal.replace(/^[#]/, ''));
        }
      }
    }
  }
  const body = content.slice(fmMatch[0].length);
  return { frontmatter: result, body };
}

// Search across all or specific vaults
export function searchVaults(query, options = {}) {
  const {
    vaultsDir = getVaultsDir(),
    vaultFilter = null,
    tagFilter = null,
    limit = 30,
    isRegex = false,
  } = options;

  const vaults = discoverVaults(vaultsDir);
  const targetVaults = vaultFilter
    ? vaults.filter((v) => v.name.toLowerCase().includes(vaultFilter.toLowerCase()))
    : vaults;

  if (targetVaults.length === 0) {
    return { vaults: [], results: [], query };
  }

  let regex = null;
  if (query) {
    try {
      regex = isRegex ? new RegExp(query, 'i') : new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    } catch {
      regex = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    }
  }

  const results = [];

  for (const v of targetVaults) {
    const files = collectMarkdownFiles(v.path);
    for (const f of files) {
      if (results.length >= limit) break;
      let rawText = '';
      try {
        rawText = readFileSync(f.fullPath, 'utf-8');
      } catch {
        continue;
      }

      const { frontmatter, body } = parseFrontmatter(rawText);

      // Check tag filter
      if (tagFilter) {
        const cleanTag = tagFilter.replace(/^#/, '').toLowerCase();
        const hasFmTag = frontmatter.tags.some((t) => t.toLowerCase() === cleanTag);
        const inlineTagRegex = new RegExp(`#${cleanTag}\\b`, 'i');
        const hasInlineTag = inlineTagRegex.test(rawText);
        if (!hasFmTag && !hasInlineTag) continue;
      }

      // Title match
      const baseTitle = basename(f.fileName, extname(f.fileName));
      const effectiveTitle = frontmatter.title || baseTitle;
      const titleMatches = regex ? regex.test(effectiveTitle) || regex.test(f.relPath) : true;

      // Body lines match
      const lines = rawText.split(/\r?\n/);
      const matchedLines = [];

      if (regex) {
        for (let i = 0; i < lines.length; i++) {
          if (regex.test(lines[i])) {
            matchedLines.push({
              lineNum: i + 1,
              content: lines[i].trim(),
            });
            if (matchedLines.length >= 3) break; // keep up to 3 snippets per file
          }
        }
      }

      if (titleMatches || matchedLines.length > 0 || tagFilter) {
        results.push({
          vault: v.name,
          vaultPath: v.path,
          filePath: f.fullPath,
          relPath: f.relPath,
          fileName: f.fileName,
          title: effectiveTitle,
          tags: frontmatter.tags,
          titleMatched: titleMatches,
          matches: matchedLines,
        });
      }
    }
  }

  return { vaults: targetVaults, results, query };
}

// Highlight matched terms in text
function highlightMatch(text, query) {
  if (!query || !text) return text;
  try {
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const rx = new RegExp(`(${escaped})`, 'gi');
    return text.replace(rx, (m) => bold(fireYellow(m)));
  } catch {
    return text;
  }
}

// CLI handler for `gabelmz vault` / `gabelmz search`
export async function runVaultCommand(args = []) {
  printCompactBanner('Obsidian Vaults Search');

  const vaultsDir = getVaultsDir();
  const subcmd = args[0] || '';

  if (subcmd === '--list' || subcmd === '-l' || subcmd === 'list') {
    const vaults = discoverVaults(vaultsDir);
    console.log(`\n${bold(fireOrange('Discovered Obsidian Vaults:'))} ${dim(`(${vaultsDir})`)}\n`);
    if (vaults.length === 0) {
      console.log(`  ${dim('No Obsidian vaults found in directory.')}`);
      console.log(`  ${dim('Set your vaults location via:')} ${fireYellow('gabelmz config set vaults_dir <path>')}\n`);
      return 0;
    }
    for (const v of vaults) {
      const files = collectMarkdownFiles(v.path);
      console.log(`  ${fireAmber('●')} ${bold(fireWhite(v.name.padEnd(20)))} ${dim(`${files.length} notes`)}  ${dim(v.path)}`);
    }
    console.log('');
    return 0;
  }

  // Parse args
  let query = '';
  let vaultFilter = null;
  let tagFilter = null;
  let limit = 25;

  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '--vault' || a === '-v') {
      vaultFilter = args[++i];
    } else if (a === '--tag' || a === '-t') {
      tagFilter = args[++i];
    } else if (a === '--limit' || a === '-n') {
      limit = parseInt(args[++i], 10) || 25;
    } else if (!a.startsWith('-')) {
      query += (query ? ' ' : '') + a;
    }
  }

  if (!query && !tagFilter && !vaultFilter) {
    console.log(`Usage:`);
    console.log(`  ${fireYellow('gabelmz vault <query>')}               Search across all Obsidian vaults`);
    console.log(`  ${fireYellow('gabelmz vault <query> --vault <name>')} Search inside a specific vault`);
    console.log(`  ${fireYellow('gabelmz vault --tag <tag>')}           Search notes by tag`);
    console.log(`  ${fireYellow('gabelmz vault list')}                   List all detected vaults\n`);
    return 0;
  }

  console.log(` ${dim('Searching vaults at')} ${cyan(vaultsDir)} ${query ? `${dim('for')} "${bold(fireYellow(query))}"` : ''}...\n`);

  const { vaults, results } = searchVaults(query, {
    vaultsDir,
    vaultFilter,
    tagFilter,
    limit,
  });

  if (results.length === 0) {
    console.log(`  ${dim('No matching notes found.')}`);
    if (vaults.length === 0) {
      console.log(`  ${dim('Tip:')} Vaults folder not found. Set it with: ${fireYellow('gabelmz config set vaults_dir <path>')}`);
    }
    console.log('');
    return 0;
  }

  console.log(` ${bold(green(`Found ${results.length} results`))} ${dim(`across ${vaults.length} vault(s)`)}:\n`);

  for (let idx = 0; idx < results.length; idx++) {
    const r = results[idx];
    const vaultBadge = badge(r.vault, fireCrimson);
    const titleText = highlightMatch(r.title, query);
    const pathText = dim(r.relPath);

    console.log(` ${fireAmber(`${idx + 1}.`)} ${vaultBadge} ${bold(fireWhite(titleText))}  ${pathText}`);

    if (r.tags && r.tags.length > 0) {
      const tagsStr = r.tags.map((t) => cyan(`#${t}`)).join(' ');
      console.log(`    ${dim('tags:')} ${tagsStr}`);
    }

    for (const m of r.matches) {
      const snippet = highlightMatch(m.content.slice(0, 140), query);
      console.log(`    ${dim(`L${m.lineNum}:`)} ${snippet}`);
    }
    console.log('');
  }

  return 0;
}
