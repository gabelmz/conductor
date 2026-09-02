/**
 * OpenRouter Free AI Chat Scaffold & Streaming Client
 * Supports free open models, live streaming, multi-turn history, and scaffold mode without API key
 */

import { createInterface } from 'node:readline';
import { getOpenRouterKey, loadConfig, saveConfig } from '../config.js';
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
  magenta,
  badge,
  box,
  bgBlack,
} from '../ui/colors.js';
import { printCompactBanner } from '../ui/skull.js';

export const FREE_MODELS = [
  {
    id: 'meta-llama/llama-3.3-70b-instruct:free',
    name: 'Llama 3.3 70B Instruct (Free)',
    provider: 'Meta',
    context: '128k',
  },
  {
    id: 'google/gemini-2.0-flash-exp:free',
    name: 'Gemini 2.0 Flash Experimental (Free)',
    provider: 'Google',
    context: '1M',
  },
  {
    id: 'deepseek/deepseek-r1:free',
    name: 'DeepSeek R1 Reasoning (Free)',
    provider: 'DeepSeek',
    context: '64k',
  },
  {
    id: 'mistralai/mistral-small-24b-instruct-2501:free',
    name: 'Mistral Small 24B (Free)',
    provider: 'Mistral',
    context: '32k',
  },
  {
    id: 'qwen/qwen-2.5-coder-32b-instruct:free',
    name: 'Qwen 2.5 Coder 32B (Free)',
    provider: 'Alibaba',
    context: '32k',
  },
];

// Ask question via readline
function promptLine(rl, query) {
  return new Promise((resolve) => rl.question(query, resolve));
}

// Scaffold simulated response generator when no key is set yet
function generateScaffoldResponse(userMsg, model) {
  const responses = [
    `🔥 [OpenRouter Scaffold Response]\n\nI received your prompt: "${userMsg}"\n\nI am running on the free model scaffold (${model}). Once you connect your free OpenRouter API key, you will get live reasoning and generation streamed directly from OpenRouter!`,
    `⚡ [OpenRouter Free Scaffold]\n\nQuery processed: "${userMsg}"\n\nTo unlock live inference with 70B+ open weights, set your API key:\n  • run: gabelmz config set openrouter_key <your-key>\n  • get free key at: https://openrouter.ai/keys`,
  ];
  return responses[Math.floor(Math.random() * responses.length)];
}

// Call live OpenRouter streaming API
async function streamOpenRouterChat({ apiKey, model, messages, onChunk, onDone, onError }) {
  try {
    const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com/gabelmz',
        'X-Title': 'gabelmz CLI',
      },
      body: JSON.stringify({
        model,
        messages,
        stream: true,
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      onError(new Error(`OpenRouter API error ${res.status}: ${errText}`));
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(':')) continue;
        if (trimmed === 'data: [DONE]') {
          onDone();
          return;
        }
        if (trimmed.startsWith('data: ')) {
          try {
            const data = JSON.parse(trimmed.slice(6));
            const delta = data.choices?.[0]?.delta?.content || '';
            if (delta) {
              onChunk(delta);
            }
          } catch {
            // Ignore parse errors on partial frames
          }
        }
      }
    }
    onDone();
  } catch (err) {
    onError(err);
  }
}

// Interactive chat loop
export async function runChatCommand(args = []) {
  printCompactBanner('OpenRouter AI Free Chat');

  const cfg = loadConfig();
  let apiKey = getOpenRouterKey();
  let currentModel = cfg.default_model || FREE_MODELS[0].id;

  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  // Check if initial single-turn prompt was passed
  const initialPrompt = args.join(' ').trim();

  // If no API key, display scaffold info banner
  if (!apiKey) {
    console.log(
      box(
        [
          `${bold(fireYellow('🔥 OPENROUTER FREE TIER AI SCAFFOLD (No Key Configured)'))}`,
          '',
          `${dim('• Current Model:')} ${cyan(currentModel)}`,
          `${dim('• Status:')}        ${fireAmber('Scaffold / Simulation Mode Active')}`,
          '',
          `${bold('How to connect your live free OpenRouter API key:')}`,
          `  1. Get a free API key at ${underline(cyan('https://openrouter.ai/keys'))}`,
          `  2. Run: ${fireYellow('gabelmz config set openrouter_key <your-key>')}`,
          `     or set environment variable ${fireYellow('OPENROUTER_API_KEY')}`,
          '',
          `${dim('You can still test the chat scaffold interactively below,')}`,
          `${dim('or type /key to input your API key right now!')}`,
        ],
        { borderColor: fireOrange }
      )
    );
    console.log('');
  } else {
    console.log(` ${green('✓')} Connected to OpenRouter Free Tier (${cyan(currentModel)})\n`);
  }

  console.log(` ${dim('Commands:')} ${cyan('/model')} switch model  ${dim('•')}  ${cyan('/key')} set API key  ${dim('•')}  ${cyan('/clear')} clear history  ${dim('•')}  ${cyan('/exit')} quit\n`);

  const history = [
    {
      role: 'system',
      content: 'You are a helpful, brilliant AI developer assistant built into the gabelmz CLI.',
    },
  ];

  async function handleUserMessage(input) {
    const trimmed = input.trim();
    if (!trimmed) return true;

    // Slash commands
    if (trimmed === '/exit' || trimmed === 'exit' || trimmed === 'quit' || trimmed === '/quit') {
      return false;
    }

    if (trimmed === '/clear') {
      history.length = 1;
      console.log(`\n ${green('✓')} Conversation history cleared.\n`);
      return true;
    }

    if (trimmed === '/key' || trimmed.startsWith('/key ')) {
      const parts = trimmed.split(' ');
      let newKey = parts[1];
      if (!newKey) {
        newKey = (await promptLine(rl, ` ${fireYellow('Enter OpenRouter API Key:')} `)).trim();
      }
      if (newKey) {
        saveConfig({ openrouter_key: newKey });
        apiKey = newKey;
        console.log(`\n ${green('✓')} OpenRouter API key saved to ~/.gabelmz/config.json!\n`);
      } else {
        console.log(`\n ${dim('No key entered. Continuing in scaffold mode.')}\n`);
      }
      return true;
    }

    if (trimmed === '/models' || trimmed === '/model') {
      console.log(`\n${bold(fireOrange('Available Free OpenRouter Models:'))}\n`);
      FREE_MODELS.forEach((m, idx) => {
        const isCurrent = m.id === currentModel;
        const mark = isCurrent ? green('● [ACTIVE]') : dim('○');
        console.log(`  ${mark} ${bold(fireWhite(m.name))}`);
        console.log(`     ${dim('ID:')} ${cyan(m.id)}  ${dim('• Context:')} ${m.context}`);
      });
      console.log('');
      const choice = (await promptLine(rl, ` ${fireYellow('Select model number (1-5) or enter model ID (or press Enter to keep current):')} `)).trim();
      if (choice) {
        const num = parseInt(choice, 10);
        if (num >= 1 && num <= FREE_MODELS.length) {
          currentModel = FREE_MODELS[num - 1].id;
        } else {
          currentModel = choice;
        }
        saveConfig({ default_model: currentModel });
        console.log(`\n ${green('✓')} Model switched to: ${cyan(currentModel)}\n`);
      }
      return true;
    }

    if (trimmed === '/help') {
      console.log(`\n ${bold('Chat Commands:')}`);
      console.log(`  ${cyan('/model')}   Switch free AI model`);
      console.log(`  ${cyan('/key')}     Configure OpenRouter API key`);
      console.log(`  ${cyan('/clear')}   Reset conversation history`);
      console.log(`  ${cyan('/exit')}    Return to menu / exit\n`);
      return true;
    }

    // Add user message
    history.push({ role: 'user', content: trimmed });

    process.stdout.write(`\n${bold(fireAmber('🤖 AI:'))} `);

    if (!apiKey) {
      // Simulate scaffold streaming response
      const scaffoldText = generateScaffoldResponse(trimmed, currentModel);
      for (const char of scaffoldText) {
        process.stdout.write(char);
        await new Promise((r) => setTimeout(r, 12));
      }
      console.log('\n');
      history.push({ role: 'assistant', content: scaffoldText });
      return true;
    }

    // Live Streaming API Call
    let assistantMessage = '';
    await new Promise((resolve) => {
      streamOpenRouterChat({
        apiKey,
        model: currentModel,
        messages: history,
        onChunk: (delta) => {
          assistantMessage += delta;
          process.stdout.write(delta);
        },
        onDone: () => {
          console.log('\n');
          history.push({ role: 'assistant', content: assistantMessage });
          resolve();
        },
        onError: (err) => {
          console.log(`\n\n ${fireRed('Error connecting to OpenRouter:')} ${err.message}`);
          console.log(` ${dim('Tip: Check your API key or model availability.')}\n`);
          resolve();
        },
      });
    });

    return true;
  }

  // If single argument provided, run once
  if (initialPrompt) {
    await handleUserMessage(initialPrompt);
    rl.close();
    return 0;
  }

  // REPL loop
  while (true) {
    const input = await promptLine(rl, `${bold(fireRed('you >'))} `);
    const continueChat = await handleUserMessage(input);
    if (!continueChat) break;
  }

  rl.close();
  console.log(`\n ${dim('Exited AI chat.')}\n`);
  return 0;
}
