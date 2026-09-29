import DesktopCompanion from './DesktopCompanion'
import Icon from './Icon'
import '../desktop-layer-preview.css'

/** Same top island; the browser cannot create OS windows or drag files to Finder. */
export default function DesktopLayerPreview() {
  return <main className="desk-preview">
    <div className="desk-preview-label"><Icon n="bx-desktop" /><span>MEMOKET / DESKTOP LAYER</span><span>交互预览</span></div>
    <div className="desk-preview-context" aria-hidden="true">
      <span className="desk-preview-context-line" />
      <p>想到就记。<br />放下，还能接着用。</p>
      <span>鼠标移向顶部，展开你的桌面口袋。</span>
    </div>
    <div className="desk-preview-top">
      <DesktopCompanion surface="top" />
    </div>
    <footer className="desk-preview-footer">
      <span><strong>只在顶部，随时接住。</strong>随手记连接本地笔记库，专注进度自动保留；跨应用拖放、剪贴板建议和窗口唤回需在桌面版使用。</span>
      <a href={`/?user=${encodeURIComponent(new URLSearchParams(location.search).get('user') || 'ui-review')}`}><Icon n="bx-book" />打开完整笔记库</a>
    </footer>
  </main>
}
