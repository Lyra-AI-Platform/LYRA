/**
 * LyraAuth — Human Intelligence Authenticator
 * Version 1.0.0
 * Copyright (C) 2026 Lyra Contributors
 *
 * Drop-in replacement for reCAPTCHA. Add to any website with one line:
 *   <script src="https://auth.lyra.ai/lyraauth.js"></script>
 *   <div class="lyraauth" data-sitekey="lyra_YOUR_KEY"></div>
 *
 * What it does:
 *   1. Shows a fun, modern challenge (not "click traffic lights")
 *   2. Proves the user is human to your backend
 *   3. Contributes one labeled training example to Lyra's AI training
 *
 * Privacy: Users are clearly told their answer trains an AI.
 * See our Privacy Policy and Terms at https://auth.lyra.ai/legal
 */

(function (window) {
  'use strict';

  const LYRAAUTH_VERSION = '1.0.0';
  // Auto-detect: use same origin in production, allow override via global var
  const API_BASE = window.LYRAAUTH_API ||
    (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
      ? 'http://' + window.location.host + '/api/auth'
      : 'https://lyraauth.com/api/auth');

  // ── Styles ──────────────────────────────────────────────────────────────────
  const CSS = `
  .lyraauth-widget {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    max-width: 400px;
    border: 1.5px solid #e2e8f0;
    border-radius: 16px;
    padding: 0;
    background: #ffffff;
    box-shadow: 0 4px 24px rgba(0,0,0,0.07);
    overflow: hidden;
    transition: all 0.3s ease;
  }
  .lyraauth-widget:hover {
    box-shadow: 0 8px 32px rgba(0,0,0,0.12);
  }
  .lyraauth-header {
    display: flex;
    align-items: center;
    padding: 14px 18px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
  }
  .lyraauth-logo {
    font-size: 22px;
    margin-right: 10px;
  }
  .lyraauth-title {
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.3px;
  }
  .lyraauth-subtitle {
    font-size: 10px;
    opacity: 0.85;
    margin-top: 1px;
  }
  .lyraauth-body {
    padding: 18px;
  }
  .lyraauth-prompt {
    font-size: 15px;
    color: #1a202c;
    line-height: 1.5;
    margin-bottom: 16px;
    font-weight: 500;
  }
  .lyraauth-options {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .lyraauth-option {
    padding: 10px 14px;
    border: 1.5px solid #e2e8f0;
    border-radius: 10px;
    cursor: pointer;
    font-size: 14px;
    color: #2d3748;
    transition: all 0.15s ease;
    background: #f8fafc;
    text-align: left;
  }
  .lyraauth-option:hover {
    border-color: #667eea;
    background: #f0f4ff;
    color: #667eea;
    transform: translateX(2px);
  }
  .lyraauth-option.selected {
    border-color: #667eea;
    background: linear-gradient(135deg, #667eea15, #764ba215);
    color: #5a67d8;
    font-weight: 600;
  }
  .lyraauth-text-input {
    width: 100%;
    padding: 10px 14px;
    border: 1.5px solid #e2e8f0;
    border-radius: 10px;
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s;
    box-sizing: border-box;
    color: #1a202c;
  }
  .lyraauth-text-input:focus {
    border-color: #667eea;
    box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
  }
  .lyraauth-submit {
    width: 100%;
    margin-top: 12px;
    padding: 11px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.1s;
    letter-spacing: 0.3px;
  }
  .lyraauth-submit:hover { opacity: 0.92; transform: translateY(-1px); }
  .lyraauth-submit:active { transform: translateY(0); }
  .lyraauth-submit:disabled { opacity: 0.5; cursor: not-allowed; }
  .lyraauth-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 18px;
    border-top: 1px solid #f0f0f0;
    background: #fafafa;
  }
  .lyraauth-footer-text {
    font-size: 10px;
    color: #a0aec0;
  }
  .lyraauth-footer-text a {
    color: #667eea;
    text-decoration: none;
  }
  .lyraauth-badge {
    font-size: 10px;
    color: #48bb78;
    display: flex;
    align-items: center;
    gap: 3px;
    font-weight: 600;
  }
  .lyraauth-success {
    padding: 28px 18px;
    text-align: center;
  }
  .lyraauth-success-icon {
    font-size: 42px;
    display: block;
    margin-bottom: 10px;
    animation: lyraauth-pop 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
  }
  .lyraauth-success-text {
    font-size: 16px;
    font-weight: 700;
    color: #276749;
    margin-bottom: 4px;
  }
  .lyraauth-success-sub {
    font-size: 12px;
    color: #68d391;
  }
  .lyraauth-loading {
    padding: 32px 18px;
    text-align: center;
    color: #a0aec0;
    font-size: 14px;
  }
  .lyraauth-spinner {
    display: inline-block;
    width: 24px;
    height: 24px;
    border: 3px solid #e2e8f0;
    border-top-color: #667eea;
    border-radius: 50%;
    animation: lyraauth-spin 0.7s linear infinite;
    margin-bottom: 10px;
  }
  @keyframes lyraauth-spin { to { transform: rotate(360deg); } }
  @keyframes lyraauth-pop {
    from { transform: scale(0); opacity: 0; }
    to   { transform: scale(1); opacity: 1; }
  }
  .lyraauth-error {
    background: #fff5f5;
    border: 1.5px solid #fc8181;
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 13px;
    color: #c53030;
    margin-top: 10px;
    display: none;
  }
  .lyraauth-training-note {
    font-size: 10px;
    color: #a0aec0;
    margin-top: 10px;
    text-align: center;
    line-height: 1.4;
  }
  .lyraauth-training-note a { color: #667eea; text-decoration: none; }
  `;

  // ── Widget Class ─────────────────────────────────────────────────────────────
  class LyraAuth {
    constructor(container, options = {}) {
      this.container = container;
      this.siteKey = options.siteKey || container.getAttribute('data-sitekey') || '';
      this.theme = options.theme || container.getAttribute('data-theme') || 'light';
      this.callback = options.callback || null;
      this.errorCallback = options.errorCallback || null;

      this.challenge = null;
      this.selectedAnswer = null;
      this.sessionId = this._generateSessionId();
      this.startTime = 0;
      this.token = null;

      this._injectStyles();
      this._render('loading');
      this._fetchChallenge();
    }

    _injectStyles() {
      if (!document.getElementById('lyraauth-styles')) {
        const style = document.createElement('style');
        style.id = 'lyraauth-styles';
        style.textContent = CSS;
        document.head.appendChild(style);
      }
    }

    _generateSessionId() {
      return 'sess_' + Math.random().toString(36).substring(2, 15);
    }

    async _fetchChallenge() {
      try {
        const res = await fetch(`${API_BASE}/challenge?site_key=${this.siteKey}`);
        if (!res.ok) throw new Error('Failed to load challenge');
        this.challenge = await res.json();
        this.startTime = Date.now();
        this._render('challenge');
      } catch (e) {
        this._render('error', 'Could not load challenge. Please refresh.');
        if (this.errorCallback) this.errorCallback(e);
      }
    }

    _render(state, errorMsg = '') {
      this.container.innerHTML = '';
      const widget = document.createElement('div');
      widget.className = 'lyraauth-widget';

      // Header
      const header = document.createElement('div');
      header.className = 'lyraauth-header';
      header.innerHTML = `
        <span class="lyraauth-logo">✦</span>
        <div>
          <div class="lyraauth-title">LyraAuth</div>
          <div class="lyraauth-subtitle">Proving you're human, training AI</div>
        </div>
      `;
      widget.appendChild(header);

      if (state === 'loading') {
        const body = document.createElement('div');
        body.className = 'lyraauth-loading';
        body.innerHTML = `<div class="lyraauth-spinner"></div><br>Loading challenge...`;
        widget.appendChild(body);
      } else if (state === 'challenge' && this.challenge) {
        widget.appendChild(this._buildChallengeBody());
      } else if (state === 'success') {
        const body = document.createElement('div');
        body.className = 'lyraauth-success';
        body.innerHTML = `
          <span class="lyraauth-success-icon">✅</span>
          <div class="lyraauth-success-text">You're verified!</div>
          <div class="lyraauth-success-sub">Your answer helps train Lyra AI ✦</div>
        `;
        widget.appendChild(body);
      } else if (state === 'error') {
        const body = document.createElement('div');
        body.className = 'lyraauth-loading';
        body.style.color = '#e53e3e';
        body.textContent = errorMsg || 'Something went wrong. Please try again.';
        widget.appendChild(body);
      }

      // Footer
      if (state !== 'success') {
        const footer = document.createElement('div');
        footer.className = 'lyraauth-footer';
        footer.innerHTML = `
          <span class="lyraauth-footer-text">
            <a href="https://auth.lyra.ai/privacy" target="_blank">Privacy</a> ·
            <a href="https://auth.lyra.ai/terms" target="_blank">Terms</a> ·
            Your answer trains Lyra AI
          </span>
          <span class="lyraauth-badge">⚡ v${LYRAAUTH_VERSION}</span>
        `;
        widget.appendChild(footer);
      }

      this.container.appendChild(widget);
    }

    _buildChallengeBody() {
      const body = document.createElement('div');
      body.className = 'lyraauth-body';

      const c = this.challenge;

      // Prompt
      const prompt = document.createElement('div');
      prompt.className = 'lyraauth-prompt';
      prompt.innerHTML = c.prompt.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      body.appendChild(prompt);

      // Answer input
      const answersDiv = document.createElement('div');
      answersDiv.className = 'lyraauth-options';

      if (c.options && c.options.length > 0) {
        // Multiple choice
        c.options.forEach(opt => {
          const btn = document.createElement('button');
          btn.className = 'lyraauth-option';
          btn.textContent = opt;
          btn.addEventListener('click', () => {
            this.selectedAnswer = opt;
            body.querySelectorAll('.lyraauth-option').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
          });
          answersDiv.appendChild(btn);
        });
      } else {
        // Free text
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'lyraauth-text-input';
        input.placeholder = 'Type your answer here...';
        input.maxLength = 100;
        input.addEventListener('input', () => {
          this.selectedAnswer = input.value;
        });
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') submitBtn.click();
        });
        answersDiv.appendChild(input);
      }

      body.appendChild(answersDiv);

      // Error box
      const errorDiv = document.createElement('div');
      errorDiv.className = 'lyraauth-error';
      errorDiv.id = 'lyraauth-error-' + this.sessionId;
      body.appendChild(errorDiv);

      // Submit
      const submitBtn = document.createElement('button');
      submitBtn.className = 'lyraauth-submit';
      submitBtn.textContent = 'Verify →';
      submitBtn.addEventListener('click', () => this._submit(submitBtn, errorDiv));
      body.appendChild(submitBtn);

      // Training transparency note
      const note = document.createElement('div');
      note.className = 'lyraauth-training-note';
      note.innerHTML = `By answering, you consent to your response being used to train Lyra AI.
        <a href="https://auth.lyra.ai/privacy" target="_blank">Learn more</a>`;
      body.appendChild(note);

      return body;
    }

    async _submit(btn, errorDiv) {
      if (!this.selectedAnswer || !this.selectedAnswer.trim()) {
        errorDiv.style.display = 'block';
        errorDiv.textContent = 'Please select or enter an answer first.';
        return;
      }

      btn.disabled = true;
      btn.textContent = 'Verifying...';
      errorDiv.style.display = 'none';

      const answerTimeMs = Date.now() - this.startTime;

      try {
        const res = await fetch(`${API_BASE}/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            challenge_id: this.challenge.id,
            session_id: this.sessionId,
            answer: this.selectedAnswer,
            answer_time_ms: answerTimeMs,
            site_key: this.siteKey,
            user_agent: navigator.userAgent,
          }),
        });

        const result = await res.json();

        if (result.success && result.token) {
          this.token = result.token;
          this._render('success');

          // Store token for form submission
          this._injectHiddenToken(result.token);

          // Call user callback
          if (this.callback) this.callback(result.token);

          // Dispatch event
          this.container.dispatchEvent(new CustomEvent('lyraauth-success', {
            detail: { token: result.token },
            bubbles: true,
          }));
        } else {
          errorDiv.style.display = 'block';
          errorDiv.textContent = 'That doesn\'t look right. Try again!';
          btn.disabled = false;
          btn.textContent = 'Try Again →';
          setTimeout(() => this._fetchChallenge(), 1500);
        }
      } catch (e) {
        errorDiv.style.display = 'block';
        errorDiv.textContent = 'Network error. Please check your connection.';
        btn.disabled = false;
        btn.textContent = 'Retry →';
      }
    }

    _injectHiddenToken(token) {
      const existing = document.getElementById('lyraauth-token-' + this.sessionId);
      if (existing) existing.remove();
      const input = document.createElement('input');
      input.type = 'hidden';
      input.id = 'lyraauth-token-' + this.sessionId;
      input.name = 'lyraauth_token';
      input.value = token;
      this.container.parentNode.insertBefore(input, this.container.nextSibling);
    }

    getToken() { return this.token; }
    reset() {
      this.token = null;
      this.selectedAnswer = null;
      this.challenge = null;
      this._render('loading');
      this._fetchChallenge();
    }
  }

  // ── Auto-initialize ──────────────────────────────────────────────────────────
  function init() {
    document.querySelectorAll('.lyraauth[data-sitekey]').forEach(el => {
      if (!el._lyraauth) {
        el._lyraauth = new LyraAuth(el);
      }
    });
  }

  // Public API
  window.LyraAuth = {
    render: (container, options) => new LyraAuth(
      typeof container === 'string' ? document.getElementById(container) : container,
      options
    ),
    init,
    version: LYRAAUTH_VERSION,
  };

  // Auto-init on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})(window);
