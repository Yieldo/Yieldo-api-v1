import { useState } from 'react'

export default function JsonViewer({ data, label }) {
  const [open, setOpen] = useState(false)
  const json = JSON.stringify(data, null, 2)

  return (
    <div className="json-box" style={{ marginTop: 12 }}>
      <div className="json-header" style={{ cursor: 'pointer' }} onClick={() => setOpen(!open)}>
        <span>{label || 'Response'} {open ? '▾' : '▸'}</span>
        <span className="status-badge s-ok">JSON</span>
      </div>
      {open && (
        <div className="json-body">
          <pre dangerouslySetInnerHTML={{ __html: highlight(json) }} />
        </div>
      )}
    </div>
  )
}

function highlight(json) {
  return json
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
    .replace(/: "(.*?)"/g, ': <span class="json-str">"$1"</span>')
    .replace(/: (\d+\.?\d*)/g, ': <span class="json-num">$1</span>')
    .replace(/: (true|false|null)/g, ': <span class="json-bool">$1</span>')
}
