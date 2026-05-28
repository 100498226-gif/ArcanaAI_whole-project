const {
  app, BrowserWindow, globalShortcut, Tray, Menu,
  nativeImage, screen, ipcMain, dialog,
} = require('electron');
const path = require('path');

// Menu bar only — hide from dock
app.dock?.hide();

let win = null;
let tray = null;

const HOTKEY = 'Control+Command+Space';
const WIN_W = 920;
const WIN_H = 560;
const MINI_W = 380;
const MINI_H = 230;

function createWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  win = new BrowserWindow({
    width: WIN_W,
    height: WIN_H,
    x: Math.round((width - WIN_W) / 2),
    y: Math.round(height * 0.18),
    frame: false,
    resizable: false,
    movable: true,
    alwaysOnTop: true,
    show: false,
    // Required so the window appears on all macOS Spaces and over fullscreen apps
    // (set again via setAlwaysOnTop + setVisibleOnAllWorkspaces after creation)
    skipTaskbar: true,
    transparent: true,
    vibrancy: 'hud',
    visualEffectState: 'active',
    roundedCorners: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
    },
  });

  // Float above fullscreen apps and appear on all macOS Spaces
  win.setAlwaysOnTop(true, 'floating');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  win.loadFile(path.join(__dirname, 'ui-dist', 'index.html'));

  // Fade when unfocused; restore on focus — window stays on screen until hotkey
  win.on('blur',  () => win.setOpacity(0.65));
  win.on('focus', () => win.setOpacity(1.0));
}

function toggleWindow() {
  if (!win) return;
  if (win.isVisible()) {
    win.hide();
  } else {
    // Re-centre on whichever display the cursor is on
    const cursor = screen.getCursorScreenPoint();
    const display = screen.getDisplayNearestPoint(cursor);
    const { x, y, width, height } = display.workArea;
    win.setPosition(
      Math.round(x + (width - WIN_W) / 2),
      Math.round(y + height * 0.18),
    );
    win.setAlwaysOnTop(true, 'floating');
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    win.setOpacity(1.0);
    win.show();
    win.focus();
  }
}

// ── Ingestion helpers ─────────────────────────────────────────────────────────
async function triggerIngest(source) {
  const apiPath = source === 'github' ? '/ingest/github' : '/ingest/notion';
  tray.setTitle('⟳');
  win?.webContents.send('ingest-status', { source, state: 'started' });
  try {
    const res = await fetch(`http://localhost:8000${apiPath}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const data = await res.json();
    tray.setTitle('');
    win?.webContents.send('ingest-status', { source, state: 'done', data });
  } catch (err) {
    tray.setTitle('');
    win?.webContents.send('ingest-status', { source, state: 'error', error: err.message });
  }
}

async function triggerLocalIngest() {
  const result = await dialog.showOpenDialog(win, {
    title: 'Select directory to ingest',
    properties: ['openDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return;
  const dirPath = result.filePaths[0];

  tray.setTitle('⟳');
  win?.webContents.send('ingest-status', { source: 'local', state: 'started' });
  try {
    const res = await fetch('http://localhost:8000/ingest/local', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: [dirPath] }),
    });
    const data = await res.json();
    tray.setTitle('');
    win?.webContents.send('ingest-status', { source: 'local', state: 'done', data });
  } catch (err) {
    tray.setTitle('');
    win?.webContents.send('ingest-status', { source: 'local', state: 'error', error: err.message });
  }
}

// Mini-mode resize/reposition
ipcMain.on('set-mini-mode', (_e, mini) => {
  if (!win) return;
  const cursor = screen.getCursorScreenPoint();
  const { x, y, width, height } = screen.getDisplayNearestPoint(cursor).workArea;
  if (mini) {
    win.setSize(MINI_W, MINI_H);
    win.setPosition(x + width - MINI_W - 16, y + height - MINI_H - 16);
  } else {
    win.setSize(WIN_W, WIN_H);
    win.setPosition(
      Math.round(x + (width - WIN_W) / 2),
      Math.round(y + height * 0.18),
    );
  }
});

// IPC from renderer
ipcMain.on('hide-window', () => win?.hide());
ipcMain.on('clear-and-hide', () => {
  win?.webContents.send('clear');
  win?.hide();
});
ipcMain.on('ingest', (_e, source) => {
  if (source === 'local') triggerLocalIngest();
  else triggerIngest(source);
});

app.whenReady().then(() => {
  createWindow();

  // ── Tray ──────────────────────────────────────────────────────────────────
  const trayIcon = nativeImage.createFromPath(path.join(__dirname, 'tray-icon.png')).resize({ width: 16, height: 16 });
  tray = new Tray(trayIcon);
  tray.setTitle('');
  tray.setToolTip(`Arcana  [${HOTKEY}]`);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: `Open Arcana   (${HOTKEY})`, click: toggleWindow },
    { type: 'separator' },
    { label: 'Update GitHub knowledge', click: () => triggerIngest('github') },
    { label: 'Update Notion knowledge', click: () => triggerIngest('notion') },
    { label: 'Update local knowledge…', click: () => triggerLocalIngest() },
    { type: 'separator' },
    { label: 'Open in Browser', click: () => require('electron').shell.openExternal('http://localhost:8000') },
    { type: 'separator' },
    { label: 'Quit Arcana', click: () => app.quit() },
  ]));
  // tray click intentionally does nothing — use the menu item or hotkey

  // ── Global hotkey ─────────────────────────────────────────────────────────
  const registered = globalShortcut.register(HOTKEY, toggleWindow);
  if (!registered) {
    console.warn(`[arcana] Could not register hotkey ${HOTKEY} — it may be taken by another app.`);
  }
});

app.on('will-quit', () => globalShortcut.unregisterAll());

// Prevent quitting when the overlay window is closed
app.on('window-all-closed', (e) => e.preventDefault());
