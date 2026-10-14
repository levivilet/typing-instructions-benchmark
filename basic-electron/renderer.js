const editor = document.querySelector('#editor')
document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    window.benchmark.save(editor.value)
  }
})
