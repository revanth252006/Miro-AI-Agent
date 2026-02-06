const { app, BrowserWindow, screen } = require('electron');
const path = require('path');

let mainWindow;

function createWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  const windowWidth = 400;
  const windowHeight = 600;

  mainWindow = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width - windowWidth - 20,
    y: height - windowHeight - 20,
    frame: false,             // No borders
    transparent: true,        // See-through
    alwaysOnTop: true,        // Floating
    resizable: false,
    skipTaskbar: false,       // Set to FALSE so you can see it in taskbar for now
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });

  // 🔴 FORCE LOCALHOST for Development
  // This ensures it connects to your running React server
  const startUrl = "http://localhost:3000"; 
  
  console.log("⚡ Loading URL:", startUrl);
  mainWindow.loadURL(startUrl);
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});