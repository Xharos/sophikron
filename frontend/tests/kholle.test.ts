import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	kholleDuration,
	kholleLoad,
	kholleMinutes,
	khollePupilMinutes
} from '../src/lib/kholle.ts';

test('weekly pupil minutes use configured group size', () => {
	assert.equal(khollePupilMinutes(900, 30, 3), 10);
	assert.equal(khollePupilMinutes(900, 30, 2), 15);
	assert.equal(khollePupilMinutes(900, 0, 3), null);
	assert.equal(khollePupilMinutes(900, 30, null), null);
});

test('decimal hours accept either separator and preserve minutes', () => {
	assert.equal(kholleMinutes('21,5'), 1290);
	assert.equal(kholleMinutes('21.5'), 1290);
	assert.equal(kholleMinutes(' 0,25 '), 15);
	assert.equal(kholleDuration(1290), '21h30');
	assert.equal(kholleDuration(3600), '60h');
	assert.equal(kholleDuration(3630), '60h30');
	assert.equal(kholleDuration(3605), '60h05');
	assert.equal(kholleDuration(0), '0h');
	for (const value of ['', '-1', 'NaN', 'Infinity', '2e3', '21:30', '0.001', '10001'])
		assert.equal(kholleMinutes(value), null, value);
});

test('team load uses every subject and every group over available weeks', () => {
	assert.deepEqual(kholleLoad([900, 900, 900, 900], 15, 30), {
		perGroup: 3600,
		total: 54000,
		weekly: 30
	});
	assert.equal(kholleLoad([900, 900, 900, 900], 10, 30).weekly, 20);
	assert.equal(kholleLoad([60], 15, 0).weekly, null);
	assert.equal(kholleLoad([60], 0, 30).weekly, 0);
});
