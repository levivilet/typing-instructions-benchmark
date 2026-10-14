const { app, BrowserWindow, ipcMain } = require('electron')
const fs = require('node:fs/promises')
const path = require('node:path')

let fixture
ipcMain.handle('save-fixture', async (_event, contents) => {
  if (typeof contents !== 'string') throw new TypeError('fixture contents must be text')
  await fs.writeFile(fixture, contents)
})

app.whenReady().then(() => {
  fixture = path.resolve(process.argv[2])
  const window = new BrowserWindow({
    width: 1000,
    height: 700,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs') },
  })
  window.loadFile(path.join(__dirname, 'index.html'))
})
