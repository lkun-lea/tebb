/** A reading preview only. The original Markdown and citations stay available in detail. */
export function noteExcerpt(body: string, title: string) {
  const lines = body.replace(/&gt;/gi, '>').split(/\r?\n/).map(line => line
    .replace(/^\s*(?:>\s*)+/, '')
    .replace(/^由伙伴聊天收藏，AI 生成；未作额外来源核验。\s*/, '')
    .replace(/^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)/, '')
    .replace(/!?\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/(\*\*|__|~~|`)(.+?)\1/g, '$2')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/&amp;/gi, '&').trim())
    .filter(line => line && line !== title && !/^(?:`{3}|~~~|[-*_]{3,}$)/.test(line));
  return lines.join(' ').slice(0, 160);
}
