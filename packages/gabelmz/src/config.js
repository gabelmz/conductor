/**
 * Configuration manager for gabelmz CLI
 * Stored at ~/.gabelmz/config.json
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

const CONFIG_DIR = join(homedir(), '.gabelmz');
const CONFIG_FILE = join(CONFIG_DIR, 'config.json');

// Smart default discovery for Vaults folder
function detectDefaultVaultPath() {
  const candidates = [
    resolve(homedir(), 'Documents', 'Development', 'Vaults'),
    resolve(homedir(), 'Documents', 'Vaults'),
    resolve(homedir(), 'Vaults'),
    resolve(homedir(), 'Obsidian'),
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return candidates[0];
}

const DEFAULT_CONFIG = {
  version: '1.0.0',
  vaults_dir: detectDefaultVaultPath(),
  openrouter_key: '',
  default_model: 'meta-llama/llama-3.3-70b-instruct:free',
  theme: 'dark-flame',
  max_search_results: 25,
};

export function getConfigPath() {
  return CONFIG_FILE;
}

export function loadConfig() {
  try {
    if (!existsSync(CONFIG_DIR)) {
      mkdirSync(CONFIG_DIR, { recursive: true });
    }
    if (!existsSync(CONFIG_FILE)) {
      writeFileSync(CONFIG_FILE, JSON.stringify(DEFAULT_CONFIG, null, 2), 'utf-8');
      return { ...DEFAULT_CONFIG };
    }
    const raw = readFileSync(CONFIG_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_CONFIG, ...parsed };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function saveConfig(updates) {
  const current = loadConfig();
  const next = { ...current, ...updates };
  if (!existsSync(CONFIG_DIR)) {
    mkdirSync(CONFIG_DIR, { recursive: true });
  }
  writeFileSync(CONFIG_FILE, JSON.stringify(next, null, 2), 'utf-8');
  return next;
}

export function getOpenRouterKey() {
  if (process.env.OPENROUTER_API_KEY && process.env.OPENROUTER_API_KEY.trim()) {
    return process.env.OPENROUTER_API_KEY.trim();
  }
  const cfg = loadConfig();
  return (cfg.openrouter_key || '').trim();
}

export function getVaultsDir() {
  if (process.env.OBSIDIAN_VAULTS_DIR && process.env.OBSIDIAN_VAULTS_DIR.trim()) {
    return resolve(process.env.OBSIDIAN_VAULTS_DIR.trim());
  }
  const cfg = loadConfig();
  return resolve(cfg.vaults_dir || detectDefaultVaultPath());
}
