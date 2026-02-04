#!/usr/bin/env node

/**
 * Weekly Fleet Update Cron Job
 * 
 * Updates AF and KL fleet data, regenerates README, and pushes to GitHub.
 * 
 * Usage:
 *   node cron-update.js                                    # Run once
 *   pm2 start cron-update.js --cron "0 6 * * 0" --no-autorestart  # Every Sunday 6am
 * 
 * Environment:
 *   AFKLM_API_KEY - API key for Air France/KLM API
 */

import { execSync, spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function log(msg) {
  console.log(`[${new Date().toISOString()}] ${msg}`);
}

function exec(cmd) {
  log(`> ${cmd}`);
  try {
    const result = execSync(cmd, { cwd: __dirname, encoding: 'utf-8' });
    if (result.trim()) console.log(result.trim());
    return true;
  } catch (error) {
    console.error(`Error: ${error.stderr || error.message}`);
    return false;
  }
}

async function runUpdate(airline) {
  return new Promise((resolve) => {
    log(`Updating ${airline} fleet...`);
    
    const child = spawn('node', ['fleet-update.js', '--airline', airline], {
      cwd: __dirname,
      env: process.env,
      stdio: 'inherit',
    });
    
    child.on('close', (code) => {
      if (code === 0) {
        log(`✅ ${airline} complete`);
        resolve(true);
      } else {
        log(`❌ ${airline} failed (code ${code})`);
        resolve(false);
      }
    });
    
    child.on('error', (err) => {
      log(`❌ ${airline} error: ${err.message}`);
      resolve(false);
    });
  });
}

async function main() {
  log('🚀 Weekly fleet update starting...\n');
  
  // Check API key
  if (!process.env.AFKLM_API_KEY && !process.env.AFKLM_API_KEYS) {
    log('❌ No API key found. Set AFKLM_API_KEY environment variable.');
    process.exit(1);
  }
  
  // Update each airline
  for (const airline of ['AF', 'KL']) {
    await runUpdate(airline);
  }
  
  // Regenerate README
  log('\n📊 Regenerating README...');
  exec('node generate-readme.js');
  
  // Check for changes
  log('\n📝 Checking for changes...');
  
  try {
    const status = execSync('git status --porcelain', { cwd: __dirname, encoding: 'utf-8' });
    
    if (!status.trim()) {
      log('✅ No changes to commit');
      return;
    }
    
    log(`Changes:\n${status}`);
    
    // Git add, commit, push
    log('\n📤 Pushing to GitHub...');
    exec('git add -A');
    
    const date = new Date().toISOString().split('T')[0];
    exec(`git commit -m "Auto-update fleet data - ${date}"`);
    exec('git push origin main');
    
    log('\n✅ Successfully pushed to GitHub!');
  } catch (error) {
    log(`Git error: ${error.message}`);
  }
  
  log('\n🏁 Done!');
}

main().catch(error => {
  log(`❌ Fatal error: ${error.message}`);
  process.exit(1);
});

