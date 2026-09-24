// A filtered Playwright context supplied to the official createConnection API.
// Page membership belongs to this connection, not to whichever Chrome tab is active.
// This is an accidental-access guardrail, NOT a browser security sandbox.
import { EventEmitter } from 'node:events';
import { randomUUID } from 'node:crypto';

export class TaskWorkspace {
  constructor(raw, browser) {
    this.raw = raw;
    this.browser = browser;
    this.events = new EventEmitter();
    this.owned = new Map();
    this.pending = new Set();
    this.cdp = null;
    this.disposed = false;
    this.onPage = page => {
      // Only popups whose opener is already owned join this workspace.
      // Manually opened user tabs are never adopted, even in the same window.
      const pending = this.adoptPopup(page).catch(() => {}).finally(() => this.pending.delete(pending));
      this.pending.add(pending);
    };
    raw.on('page', this.onPage);
    this.context = new Proxy(raw, { get: (target, key) => {
      if (key === 'pages') return () => this.pages();
      if (key === 'newPage') return () => this.newPage();
      if (key === 'close') return async () => { throw new Error('Personal Chrome context is not owned by Mac Bridge.'); };
      if (['on', 'once', 'addListener', 'removeListener', 'off'].includes(key)) {
        return (event, listener) => {
          if (event === 'page') this.events[key](event, listener);
          else target[key](event, listener);
          return this.context;
        };
      }
      const value = Reflect.get(target, key, target);
      return typeof value === 'function' ? value.bind(target) : value;
    }});
  }
  pages() { return [...this.owned.keys()].filter(page => !page.isClosed()); }
  async session() {
    if (!this.cdp) this.cdp = await this.browser.newBrowserCDPSession();
    return this.cdp;
  }
  async identity(page) {
    const session = await this.raw.newCDPSession(page);
    try {
      const { targetInfo } = await session.send('Target.getTargetInfo');
      const { windowId } = await (await this.session()).send('Browser.getWindowForTarget', { targetId: targetInfo.targetId });
      return { targetId: targetInfo.targetId, windowId };
    } finally { await session.detach(); }
  }
  add(page, identity) {
    if (this.owned.has(page) || this.disposed || page.isClosed()) return;
    const original = page.bringToFront;
    // Upstream tab selection calls bringToFront; selection here is LOGICAL ONLY.
    // No global mouse/keyboard, activation or focus restoration is used.
    page.bringToFront = async () => {};
    this.owned.set(page, { ...identity, original });
    page.once('close', () => this.owned.delete(page));
    this.events.emit('page', page);
  }
  async adoptPopup(page) {
    const opener = await page.opener();
    if (!opener || !this.owned.has(opener)) return;
    const id = await this.identity(page);
    // A popup can have its own window; it still needs an owned opener.
    this.add(page, id);
  }
  async newPage() {
    if (this.disposed) throw new Error('Browser workspace has been closed.');
    const marker = 'about:blank#mac-bridge-' + randomUUID();
    const session = await this.session();
    const { targetId } = await session.send('Target.createTarget', {
      url: marker, newWindow: true, background: true, width: 1280, height: 800
    });
    try {
      // Wait only for our own unique target. Never select the user's current tab.
      const deadline = Date.now() + 10000;
      while (Date.now() < deadline) {
        const page = this.raw.pages().find(p => p.url() === marker);
        if (page) {
          const id = await this.identity(page);
          if (id.targetId !== targetId) throw new Error('Task page identity changed.');
          this.add(page, id);
          return page;
        }
        await new Promise(resolve => setTimeout(resolve, 25));
      }
      throw new Error('Chrome did not create the separate task window.');
    } catch (error) {
      // This is the target we just created, never a pre-existing user page.
      await session.send('Target.closeTarget', { targetId }).catch(() => {});
      throw error;
    }
  }
  async validate() {
    await Promise.all([...this.pending]);
    for (const [page, identity] of this.owned) {
      if (page.isClosed()) continue;
      const { windowId } = await (await this.session()).send('Browser.getWindowForTarget', { targetId: identity.targetId });
      if (windowId !== identity.windowId)
        throw new Error('A task tab was moved to another window. Close the bridge connection and start a new task; no input was sent.');
    }
  }
  status() {
    return { separate_task_windows: true, tabs_scope: 'connection-owned pages only',
      task_pages: this.pages().length, focus_policy: 'background creation; no bringToFront',
      task_window_ids: [...new Set([...this.owned.values()].map(x => x.windowId))] };
  }
  dispose() {
    this.disposed = true;
    this.raw.off('page', this.onPage);
    for (const [page, { original }] of this.owned) page.bringToFront = original;
    this.events.removeAllListeners();
    // Keep task tabs for inspection; do not close browser, profile or user pages.
  }
}
