"""Single-change diagnostic probes for the pinned packaged LVCE release."""
import hashlib

PROBES = {
    'css-dirty-dot': ('css/App.css', (
        ('\n.MaskIconCircleFilled,\n.IconCircleFilled {',
         '\n.EditorTabCloseButton .MaskIconCircleFilled {\n'
         '  mask-image: radial-gradient(circle closest-side, #000 47%, transparent 53%);\n'
         '}\n\n.MaskIconCircleFilled,\n.IconCircleFilled {'),
    )),
    'no-keyup-rpc': ('rendererProcessMain.js', (
        ("    if (rpc) {\n      if (getRpcId(uid) === 'Editor' && args[0] !== 'handleBlur' && args[0] !== 'handleFocus') {",
         "    if (rpc) {\n      const isEditor = getRpcId(uid) === 'Editor';\n"
         "      if (isEditor && args[0] === 'handleKeyUp' && args[1] !== 'Alt') return;\n"
         "      if (isEditor && args[0] !== 'handleBlur' && args[0] !== 'handleFocus') {"),
    )),
    'no-provider-refresh': ('editorWorkerMain.js', (
        ('textDecorations: await getEditorTextDecorations(nextState)', 'textDecorations: []'),
        ('const updateDiagnostics = async (editor, timeoutMs = 0) => {',
         'const updateDiagnostics = async (editor, timeoutMs = 0) => {\n  return editor;'),
        ('const gutterDecorations = await getEditorGutterDecorations(snapshot);', 'const gutterDecorations = [];'),
    )),
}


def apply_probe(variant_path, probe):
    glob, edits = PROBES[probe]
    path, = variant_path.rglob(glob)
    original = path.read_bytes()
    patched = original.decode()
    for before, after in edits:
        if patched.count(before) != 1:
            raise ValueError(f'probe {probe} did not match {glob} once')
        patched = patched.replace(before, after)
    candidate = patched.encode()
    path.write_bytes(candidate)
    return {
        'path': str(path.relative_to(variant_path)),
        'releaseSha256': hashlib.sha256(original).hexdigest(),
        'probeSha256': hashlib.sha256(candidate).hexdigest(),
    }
