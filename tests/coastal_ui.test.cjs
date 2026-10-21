const {test} = require('node:test');
const assert = require('node:assert/strict');
const tracker = require('../static/coastal.js');
const row = {id: 'id', muni: 'A&B', no: '1', deal: 'sale', price: 100,
  source_url: 'https://example.invalid/?a=1&b=2', first_seen_at: '2026-10-21T17:00:00Z',
  geo: {status: 'ok', coast_km: 5, airport_drive_minutes: 90}};
const filters = {max_coast_km: 5, max_airport_minutes: 90, price_cap_yen: 100};
test('same inclusive coast/airport/price rules as Python', () => {
  assert.equal(tracker.matches(row, filters), true);
  assert.equal(tracker.matches({...row, price: null}, filters), false);
  assert.equal(tracker.matches({...row, deal: 'rent'}, filters), false);
  assert.equal(tracker.matches({...row, geo: {status: 'pending'}}, filters), false);
  assert.equal(tracker.matches(row, {...filters, max_coast_km: 4.99}), false);
  assert.equal(tracker.matches({...row, price: 0}, {...filters, price_cap_yen: 0}), true);
});
test('new feed excludes old, future and unzoned first-seen dates', () => {
  const rows = [row, {...row, first_seen_at: '2026-10-20T18:00:00Z'},
    {...row, first_seen_at: '2026-10-20T17:59:59Z'}, {...row, first_seen_at: '2026-10-21T18:00:01Z'},
    {...row, first_seen_at: '2026-10-21T17:00:00'}, {...row, first_seen_at: null}];
  assert.equal(tracker.fresh(rows, '2026-10-21T18:00:00Z').length, 2);
});
test('RSS escapes source URLs and text', () => {
  const text = tracker.rss([row], filters, '2026-10-21T18:00:00Z', 'Estimate');
  assert.match(text, /A&amp;B/);
  assert.match(text, /a=1&amp;b=2/);
  assert.match(text, /isPermaLink="false">id/);
});
