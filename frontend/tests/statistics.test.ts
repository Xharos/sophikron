import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	byteLabel,
	chartMaximum,
	linePoints,
	timeLabels,
	breakdownSeries,
	pointBounds,
	type ChartSeries
} from '../src/lib/statistics.ts';

test('visible chart series determine scale and preserve zeros without NaN', () => {
	const series: ChartSeries[] = [
		{ key: 'all', label: 'Tentatives', color: '#244bc1', values: [0, 91, 30] },
		{ key: 'unique', label: 'Comptes uniques', color: '#2d8b72', values: [0, 3, 1] }
	];
	assert.equal(chartMaximum(series), 91);
	assert.equal(chartMaximum(series.filter((item) => item.key !== 'all')), 3);
	assert.equal(chartMaximum([]), 1);
	assert.equal(chartMaximum([{ ...series[0], values: [0, 0] }]), 1);
	assert.equal(linePoints([0, 3, 0], 3), '44,184 277,24 510,184');
	assert.equal(linePoints([0], 1), '44,184');
	assert.ok(!linePoints([], 1).includes('NaN'));
});

test('nonzero peaks always reach the full chart height and bar width', () => {
	for (const peak of [0.5, 1, 2, 3, 7, 91, 100, 1025]) {
		const maximum = chartMaximum([
			{ key: 'downloads', label: 'Downloads', color: '#244bc1', values: [0, peak, 0] }
		]);
		assert.equal(maximum, peak);
		assert.equal(linePoints([0, peak, 0], maximum), '44,184 277,24 510,184');
		assert.equal((peak / maximum) * 100, 100);
	}
});

test('point hit targets stay inside the plot on short and mobile charts', () => {
	for (const count of [1, 2, 7, 23, 25, 30]) {
		const bounds = Array.from({ length: count }, (_, index) => pointBounds(index, count));
		assert.equal(bounds[0].x, 44);
		assert.equal(bounds.at(-1)!.x + bounds.at(-1)!.width, 510);
		assert.ok(bounds.every((item) => item.x >= 44 && item.width > 0 && item.x + item.width <= 510));
	}
});

test('storage units and shared breakdown contracts use the same formatting everywhere', () => {
	assert.equal(byteLabel(0), '0 o');
	assert.equal(byteLabel(1024), '1 Kio');
	assert.equal(byteLabel(1048576), '1 Mio');
	assert.equal(byteLabel(1073741824), '1 Gio');
	assert.deepEqual(
		breakdownSeries([{ id: null, label: 'PDF', value: 42, count: 2 }])[0].values,
		[42]
	);
});

test('Paris hourly labels distinguish the repeated autumn hour in point details', () => {
	const hours = ['2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z'];
	assert.deepEqual(timeLabels(hours, 'day'), ['02:00', '02:00']);
	const details = timeLabels(hours, 'day', true);
	assert.notEqual(details[0], details[1]);
	assert.ok(timeLabels(['2026-10-25T23:00:00Z'], 'week')[0].includes('26'));
});
