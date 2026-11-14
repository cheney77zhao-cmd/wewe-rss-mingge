// Run with Node 24+ (native TypeScript stripping).
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const root = process.argv[2] || path.resolve(__dirname, '..');
const paths = ['apps/web/src/utils/article-url.ts', 'apps/server/src/feeds/article-url.ts'];
const oldId = 'WR' + 'x'.repeat(70);
const ids = [oldId, 'WR' + 'b'.repeat(70), 'MP_WXS_456_WR' + 'c'.repeat(70)];
for (const file of paths) {
  const { articleUrl } = require(path.join(root, file));
  for (const id of ids) {
    assert.equal(articleUrl(id), '/feeds/article/' + encodeURIComponent(id) + '/original');
    assert.equal(articleUrl(id, 'https://app.example/'), 'https://app.example/feeds/article/' + encodeURIComponent(id) + '/original');
  }
  for (const id of ['f9NSNDchorq7YgSdx9_TqA', 'normal_A-b~c', 'WR' + 'a'.repeat(20)]) {
    assert.equal(articleUrl(id), 'https://mp.weixin.qq.com/s/' + id);
  }
  assert.equal(articleUrl('MP_WXS_123_short'), 'https://mp.weixin.qq.com/s/short');
}
assert.equal(fs.readFileSync(path.join(root, paths[0]), 'utf8'), fs.readFileSync(path.join(root, paths[1]), 'utf8'));
console.log('PASS: 20 URL cases; generic WR routing; ordinary IDs unchanged; client/server parity.');
