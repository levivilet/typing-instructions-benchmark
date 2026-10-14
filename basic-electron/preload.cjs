const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('benchmark', {
  save: (contents) => ipcRenderer.invoke('save-fixture', contents),
})
