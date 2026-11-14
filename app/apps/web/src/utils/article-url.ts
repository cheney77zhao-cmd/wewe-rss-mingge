// WR references are opaque WeRead IDs, not WeChat short-link tokens.
export function isWeReadReference(id: string): boolean {
  return /^WR[A-Za-z0-9_~-]{23,}$/.test(id.replace(/^MP_WXS_[0-9]+_/, ''));
}

export function articleUrl(id: string, origin = ''): string {
  if (isWeReadReference(id)) {
    return `${origin.replace(/\/$/, '')}/feeds/article/${encodeURIComponent(id)}/original`;
  }
  return `https://mp.weixin.qq.com/s/${id.replace(/^MP_WXS_[0-9]+_/, '')}`;
}
