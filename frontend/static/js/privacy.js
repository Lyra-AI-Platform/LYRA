/**
 * Lyra AI Platform — Privacy & Consent Management
 * Copyright (C) 2026 Lyra Contributors — All Rights Reserved.
 * See LICENSE for terms.
 */

const CONSENT_KEY = 'lyra_consent_v1';

// ─── First-Run Consent ───

document.addEventListener('DOMContentLoaded', () => {
  const consent = localStorage.getItem(CONSENT_KEY);
  if (!consent) {
    // First run — show consent overlay
    setTimeout(() => {
      document.getElementById('consentOverlay').style.display = 'flex';
    }, 800);
  }
});

function acceptConsent() {
  const collective = document.getElementById('collectiveConsent').checked;

  localStorage.setItem(CONSENT_KEY, JSON.stringify({
    accepted_at: new Date().toISOString(),
    collective_intelligence: collective,
    version: '1.0',
  }));

  // Apply consent choice
  if (collective) {
    fetch('/api/telemetry/opt-in', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    }).catch(() => {});
  }

  // Hide overlay with animation
  const overlay = document.getElementById('consentOverlay');
  overlay.style.opacity = '0';
  overlay.style.transition = 'opacity 0.4s';
  setTimeout(() => { overlay.style.display = 'none'; }, 400);

  if (collective) {
    showToast('✓ Collective Intelligence enabled — thank you for contributing!');
  } else {
    showToast('✓ Lyra is ready. All data stays on your machine.');
  }
}

// ─── Privacy Settings Panel ───

async function openPrivacySettings() {
  document.getElementById('privacyModal').style.display = 'flex';
  await loadPrivacyStatus();
}

async function loadPrivacyStatus() {
  try {
    const resp = await fetch('/api/telemetry/status');
    const data = await resp.json();

    const statusEl = document.getElementById('privacyStatus');
    statusEl.innerHTML = `
      <div class="privacy-status-row">
        <span>Collective Intelligence</span>
        <span class="${data.enabled ? 'status-ok' : 'status-warn'}">
          ${data.enabled ? '✅ Enabled' : '⭕ Disabled'}
        </span>
      </div>
      ${data.enabled ? `
        <div class="privacy-status-row">
          <span>Installation ID</span>
          <span style="font-family:monospace;font-size:11px;color:var(--text-muted)">${data.installation_id?.slice(0,8)}...&nbsp;<em>(random, not personal)</em></span>
        </div>
        <div class="privacy-status-row">
          <span>Pending Topics</span>
          <span>${data.pending_topics} keywords queued</span>
        </div>
        <div class="privacy-status-row">
          <span>Last Sync</span>
          <span>${data.last_send || 'Not yet'}</span>
        </div>
      ` : ''}
    `;

    const optinArea = document.getElementById('privacyOptinArea');
    if (data.enabled) {
      optinArea.innerHTML = `
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
          <span style="font-size:13px;color:var(--text-secondary)">Currently: <strong style="color:var(--success)">Enabled</strong></span>
          <button class="btn-danger" onclick="disableCollective()">Opt Out & Delete Data</button>
        </div>
        <button class="btn-small" onclick="syncNow()">Sync Now</button>
      `;
    } else {
      optinArea.innerHTML = `
        <div style="margin-bottom:12px;font-size:13px;color:var(--text-secondary)">Currently: <strong>Disabled</strong> — your data stays local.</div>
        <button class="btn-primary" onclick="enableCollective()">Enable Collective Intelligence</button>
        <p style="font-size:12px;color:var(--text-muted);margin-top:8px">Only anonymous topic keywords will be shared.</p>
      `;
    }
  } catch (e) {
    console.error('Failed to load privacy status:', e);
  }
}

async function enableCollective() {
  await fetch('/api/telemetry/opt-in', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  showToast('✅ Collective Intelligence enabled');
  await loadPrivacyStatus();

  // Update local consent record
  const consent = JSON.parse(localStorage.getItem(CONSENT_KEY) || '{}');
  consent.collective_intelligence = true;
  localStorage.setItem(CONSENT_KEY, JSON.stringify(consent));
}

async function disableCollective() {
  if (!confirm(
    'Opt out of Collective Intelligence?\n\n' +
    'Your locally stored telemetry data will be deleted immediately.\n' +
    'Your past anonymous contributions cannot be removed from the aggregate pool ' +
    '(they were never linked to you).'
  )) return;

  await fetch('/api/telemetry/opt-out', { method: 'POST' });
  showToast('⭕ Opted out. All local telemetry data deleted.');
  await loadPrivacyStatus();

  const consent = JSON.parse(localStorage.getItem(CONSENT_KEY) || '{}');
  consent.collective_intelligence = false;
  localStorage.setItem(CONSENT_KEY, JSON.stringify(consent));
}

async function syncNow() {
  showToast('🔄 Syncing with community server...');
  try {
    const resp = await fetch('/api/telemetry/sync-now', { method: 'POST' });
    const data = await resp.json();
    if (data.success) {
      showToast('✅ Sync complete');
    } else {
      showToast(`❌ Sync failed: ${data.message || 'check server'}`, 'error');
    }
    await loadPrivacyStatus();
  } catch (e) {
    showToast('❌ Sync error', 'error');
  }
}

// ─── Full Privacy Policy ───

async function openPrivacyPolicy() {
  openFullPrivacyPolicy();
}

async function openFullPrivacyPolicy() {
  document.getElementById('privacyPolicyModal').style.display = 'flex';
  const body = document.getElementById('privacyPolicyBody');

  // Fetch and render the privacy policy
  try {
    const resp = await fetch('/static/PRIVACY_POLICY.md');
    if (resp.ok) {
      const md = await resp.text();
      body.innerHTML = marked.parse(md);
    } else {
      body.innerHTML = `
        <p>Full privacy policy available at: <br>
        <a href="https://github.com/your-username/lyra/blob/main/PRIVACY_POLICY.md" target="_blank">
          github.com/your-username/lyra/blob/main/PRIVACY_POLICY.md
        </a></p>
      `;
    }
  } catch (e) {
    body.innerHTML = `<p>See <strong>PRIVACY_POLICY.md</strong> in the Lyra installation folder.</p>`;
  }
}
