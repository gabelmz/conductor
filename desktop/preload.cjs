/**
 * Preload — exposes safe window controls to the renderer via contextBridge.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  isDesktop: true,
  minimize: () => ipcRenderer.send('win:minimize'),
  maximize: () => ipcRenderer.send('win:maximize'),
  toggleMaximize: () => ipcRenderer.send('win:toggle-maximize'),
  close: () => ipcRenderer.send('win:close'),
  isMaximized: () => ipcRenderer.invoke('win:is-maximized'),
  openExternal: (url) => ipcRenderer.send('win:open-external', url),
  onLoadStatus: (cb) => ipcRenderer.on('load:status', (_e, msg) => cb(msg)),
  onLoadError: (cb) => ipcRenderer.on('load:error', (_e, msg) => cb(msg)),
  // Provider keys (LAW port): encrypt/decrypt through the OS keychain
  // (safeStorage/DPAPI). The renderer sees ciphertext when setting and gets
  // plaintext only per-request; nothing is ever written to disk in plaintext
  // when encryption is available.
  keys: {
    set: (providerId, apiKey) => ipcRenderer.invoke('keys:set', providerId, apiKey),
    get: (providerId) => ipcRenderer.invoke('keys:get', providerId),
    has: (providerId) => ipcRenderer.invoke('keys:has', providerId),
  },
});
