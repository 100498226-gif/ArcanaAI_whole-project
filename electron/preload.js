const { contextBridge, ipcRenderer } = require('electron');

const SERVER = 'http://localhost:8000';

contextBridge.exposeInMainWorld('electronAPI', {
  serverUrl: SERVER,
  hide: () => ipcRenderer.send('hide-window'),
  clearAndHide: () => ipcRenderer.send('clear-and-hide'),
  ingest: (source) => ipcRenderer.send('ingest', source),
  onClear: (cb) => ipcRenderer.on('clear', (_e) => cb()),
  onIngestStatus: (cb) => ipcRenderer.on('ingest-status', (_e, data) => cb(data)),
  setMiniMode: (mini) => ipcRenderer.send('set-mini-mode', mini),
  getSettings: () =>
    fetch(`${SERVER}/settings/`).then((r) => r.json()),
  updateSettings: (patch) =>
    fetch(`${SERVER}/settings/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }).then((r) => r.json()),
});
